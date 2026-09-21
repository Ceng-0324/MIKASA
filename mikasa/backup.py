"""Offline managed-runtime snapshots, using Hermes for SQLite consistency."""
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from .errors import Conflict, MikasaError
from .kanban import Kanban
from .maintenance import runtime_lock
from .native import HERMES_REVISION, verify_source
from .process import clean_env, run
from .workspace import sensitive

ROOTS = {'mikasa.sqlite3', 'kanban', 'scheduler', 'native', 'engineering', 'workspaces'}
TRANSIENT = {'__pycache__', '.cache', 'cache', 'logs', 'backups', '.DS_Store'}
CREDENTIALS = {'vault', 'tokens.json', '.netrc', '.git-credentials'}


def excluded(path):
    # Git objects and reflogs are part of the recovery state, not disposable logs.
    return (sensitive(path.as_posix()) or bool(set(path.parts) & CREDENTIALS) or
            (path.parts[0] != 'workspaces' and '.git' not in path.parts and (bool(set(path.parts) & TRANSIENT) or
             path.name.endswith(('.log', '.lock', '.pid', '.pyc', '-wal', '-shm', '-journal')))))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def new_target(destination, outside):
    target = Path(destination).absolute()
    if target.exists() or target.is_symlink():
        raise MikasaError('目标目录已存在，拒绝覆盖')
    target = target.resolve()
    if target.is_relative_to(outside.resolve()) or outside.resolve().is_relative_to(target):
        raise MikasaError('备份和恢复目标必须位于源目录之外')
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def native_copy(config, files, *, relocation=None):
    sdk = Kanban(config)
    verify_source(sdk.source)
    with tempfile.TemporaryDirectory(prefix='mikasa-backup-sdk-') as home:
        result = run([str(sdk.python.absolute()), str(config.root / 'workers/hermes/backup_adapter.py')],
                     cwd=home, env=clean_env({'HERMES_HOME': home, 'MIKASA_HERMES_SOURCE': str(sdk.source)}),
                     stdin=json.dumps({'files': files, 'relocation': relocation}),
                     timeout=max(60, len(files) * 12))
    if result['code']:
        raise MikasaError('原生备份或恢复校验失败；源状态未覆盖')


def backup_state(service, destination):
    try:
        return _backup_state(service, destination)
    except (OSError, ValueError, RuntimeError):
        raise MikasaError('备份失败；检查源文件与目标权限，源状态未覆盖') from None


def _backup_state(service, destination):
    runtime = service.config.runtime
    target = new_target(destination, runtime)
    service.tasks.call('prepare')
    with runtime_lock(runtime, exclusive=True), ExitStack() as locks:
        # Also detect a still-running pre-maintenance-lock version.
        paths = [runtime / 'runner.lock', runtime / 'kanban/adapter.lock', runtime / 'scheduler/adapter.lock']
        for root in ('native', 'engineering'):
            paths.extend((runtime / root).glob('*/mikasa.lock'))
        for path in paths:
            if path.is_symlink():
                raise MikasaError('运行锁不能为符号链接')
            if not path.exists():
                continue
            lock = locks.enter_context(path.open('a'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Conflict('原生运行状态正在使用；停服后再备份') from None
        with tempfile.TemporaryDirectory(prefix='.mikasa-backup-', dir=target.parent) as staging:
            stage = Path(staging)
            entries, files = {}, []

            def collect(source):
                relative = source.relative_to(runtime)
                if excluded(relative):
                    return
                name = relative.as_posix()
                output = stage / relative
                mode = source.lstat().st_mode
                if stat.S_ISLNK(mode):
                    linked = source.resolve(strict=True)
                    if not linked.is_relative_to(runtime.resolve()):
                        raise MikasaError('备份包含外部符号链接；未读取其内容')
                    entries[name] = {'link': linked.relative_to(runtime.resolve()).as_posix()}
                elif stat.S_ISDIR(mode):
                    output.mkdir(mode=0o700)
                    entries[name] = {'directory': True}
                    for child in sorted(source.iterdir()):
                        collect(child)
                elif stat.S_ISREG(mode):
                    entries[name] = {'mode': 0o700 if mode & 0o111 else 0o600}
                    files.append({'source': str(source), 'target': str(output),
                                  'workspace': relative.parts[0] == 'workspaces',
                                  'config': source.name == 'config.yaml' and relative.parts[0] != 'workspaces'})
                else:
                    raise MikasaError('备份中存在不支持的特殊文件')

            for name in sorted(ROOTS):
                source = runtime / name
                if source.exists() or source.is_symlink():
                    collect(source)
            for entry in entries.values():
                if 'link' in entry and (entry['link'] not in entries or 'link' in entries[entry['link']]):
                    raise MikasaError('符号链接目标未包含在备份中')
            native_copy(service.config, files)
            for name, entry in entries.items():
                if 'mode' in entry:
                    output = stage / name
                    output.chmod(entry['mode'])
                    entry.update(size=output.stat().st_size, sha256=digest(output))
            manifest = {'version': 2, 'scope': 'managed-runtime', 'hermes_revision': HERMES_REVISION,
                        'source_runtime': str(runtime.resolve()), 'source_root': str(service.config.root),
                        'entries': entries, 'local_api_identity_included': True,
                        'excluded': ['external-credentials', 'credential-files', 'logs', 'caches', 'locks', 'unmanaged-roots']}
            marker = stage / 'manifest.json'
            marker.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            marker.chmod(0o600)
            stage.rename(target)
    return {'backup': str(target), 'scope': manifest['scope'], 'entries': len(entries)}


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise MikasaError('备份清单路径无效')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path) != name or path.parts[0] not in ROOTS:
        raise MikasaError('备份清单路径越界')
    return path


def restore_state(config, source, destination):
    backup = Path(source).absolute()
    try:
        if backup.is_symlink() or (backup / 'manifest.json').is_symlink():
            raise MikasaError('备份目录与清单不能为符号链接')
        manifest = json.loads((backup / 'manifest.json').read_text())
        if (manifest['version'] != 2 or manifest['scope'] != 'managed-runtime' or
                manifest['hermes_revision'] != HERMES_REVISION):
            raise MikasaError('备份版本或 Hermes 版本不匹配')
        entries = manifest['entries']
        if not isinstance(entries, dict) or not {'mikasa.sqlite3', 'kanban/kanban.db'} <= entries.keys():
            raise MikasaError('备份缺少配对的任务与回执数据库')
        for name, entry in entries.items():
            path = safe_name(name)
            if not isinstance(entry, dict):
                raise MikasaError('备份清单条目无效')
            for parent in path.parents:
                if str(parent) != '.' and entries.get(str(parent)) != {'directory': True}:
                    raise MikasaError('备份清单缺少父目录')
            physical = backup / path
            if physical.is_symlink() or any((backup / p).is_symlink() for p in path.parents):
                raise MikasaError('备份实体不能为符号链接')
            if set(entry) == {'link'}:
                safe_name(entry['link'])
                if entry['link'] not in entries or 'link' in entries[entry['link']]:
                    raise MikasaError('备份链接缺少实体目标')
            elif entry == {'directory': True}:
                if not physical.is_dir():
                    raise MikasaError('备份目录缺失')
            elif (set(entry) == {'mode', 'size', 'sha256'} and entry['mode'] in (0o600, 0o700)
                  and physical.is_file() and physical.stat().st_size == entry['size'] and digest(physical) == entry['sha256']):
                pass
            else:
                raise MikasaError('备份内容校验失败')
        target = new_target(destination, backup)
        # A new tree is assembled privately; a failed restore never publishes a runtime.
        with tempfile.TemporaryDirectory(prefix='.mikasa-restore-', dir=target.parent) as staging:
            stage = Path(staging)
            files = []
            for name in sorted(entries, key=lambda n: (len(PurePosixPath(n).parts), n)):
                entry = entries[name]
                output = stage / name
                if 'directory' in entry:
                    output.mkdir(mode=0o700)
                elif 'mode' in entry:
                    files.append({'source': str(backup / name), 'target': str(output),
                                  'workspace': PurePosixPath(name).parts[0] == 'workspaces',
                                  'config': Path(name).name == 'config.yaml' and PurePosixPath(name).parts[0] != 'workspaces'})
            native_copy(config, files, relocation={
                'old_runtime': manifest['source_runtime'], 'runtime': str(target),
                'old_root': manifest['source_root'], 'root': str(config.root), 'stage': str(stage)})
            for name, entry in entries.items():
                if 'mode' in entry:
                    (stage / name).chmod(entry['mode'])
                elif 'link' in entry:
                    (stage / name).symlink_to(os.path.relpath(stage / entry['link'], (stage / name).parent))
            stage.rename(target)
        return {'restored': str(target), 'scope': manifest['scope'], 'entries': len(entries),
                'note': '未启动服务；重新提供外部配置与凭据，核对恢复状态后启用'}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        raise MikasaError('备份或恢复失败；检查清单、文件与目标权限，源状态未覆盖') from None
