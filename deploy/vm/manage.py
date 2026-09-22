#!/usr/bin/env python3
"""Dedicated VM operations. Restic owns snapshots; systemd owns services."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import secrets
import shutil
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time

APP = Path('/opt/mikasa')
RELEASES = Path('/opt/mikasa-releases')
STATE = Path('/var/lib/mikasa')
BACKUP_ENV = Path('/etc/mikasa-backup')
SERVICE = 'mikasa-gateway.service'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def live_state():
    states = []
    for path in (STATE / 'native').glob('*/gateway_state.json'):
        value = json.loads(path.read_text())
        pid = value.get('pid', 0)
        if pid and Path(f'/proc/{pid}').exists():
            value['_home'] = str(path.parent)
            states.append(value)
    return states


def healthy():
    if subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode:
        return False
    states = live_state()
    identity = sha(APP / 'identity.md')
    markers = list((STATE / 'native').glob('*/policy-loaded.json'))
    return bool(states and markers) and all(
        s.get('gateway_state') == 'running' and all(
            s.get('platforms', {}).get(p, {}).get('state') == 'connected'
            for p in ('feishu', 'weixin')) for s in states
    ) and all(json.loads(p.read_text()).get('soul_sha256') == identity for p in markers)


def wait_healthy(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if healthy():
            return
        time.sleep(2)
    raise RuntimeError('Gateway、双平台连接或身份加载未通过健康检查')


def start_service():
    run('systemctl', 'reset-failed', SERVICE)
    run('systemctl', 'start', SERVICE)


@contextlib.contextmanager
def drained(states, timeout=30):
    """Hermes closes admission before we check that the in-flight set is empty."""
    homes = [Path(s['_home']) for s in states]
    marked = []
    try:
        for home in homes:
            if (home / '.drain_request.json').exists():
                raise RuntimeError('已有原生维护请求；不覆盖其他维护者')
            run('runuser', '-u', 'mikasa', '--', '/opt/hermes-venv/bin/python', '-B', '-c',
                'import sys; sys.path.insert(0,"/opt/hermes"); '
                'from pathlib import Path; from gateway.drain_control import write_drain_request; '
                'write_drain_request(home=Path(sys.argv[1]), principal="mikasa-maintenance", suppress_notification=True)',
                str(home), capture_output=True)
            marked.append(home)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = live_state()
            if {s['_home'] for s in current} == set(map(str, homes)) and all(
                    s.get('gateway_state') == 'draining' and s.get('active_agents') == 0 for s in current):
                yield
                return
            time.sleep(1)
        raise RuntimeError('原生排空未完成；取消维护，任务继续运行')
    finally:
        for home in marked:
            (home / '.drain_request.json').unlink(missing_ok=True)


@contextlib.contextmanager
def stopped():
    """Drain admission, stop Gateway, then lock all managed entrypoints."""
    active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0
    states = live_state()
    if active and (not states or any(s.get('active_agents') or s.get('active_work') for s in states)):
        raise RuntimeError('Gateway 未就绪或存在任务；稍后重试维护')
    did_stop = False
    try:
        with drained(states) if active else contextlib.nullcontext():
            if active:
                did_stop = True
                run('systemctl', 'stop', SERVICE)
            with (STATE / 'maintenance.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with contextlib.ExitStack() as stack:
                    for root in ('native', 'engineer', 'engineering'):
                        for path in (STATE / root).glob('*/mikasa.lock'):
                            profile_lock = stack.enter_context(path.open('a'))
                            fcntl.flock(profile_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    yield
    finally:
        if did_stop:
            start_service()


def restic(*args, capture=False):
    env = dict(os.environ, RESTIC_REPOSITORY=str(Path('/var/backups/mikasa-restic')),
               RESTIC_PASSWORD_FILE=str(BACKUP_ENV / 'password'),
               RESTIC_CACHE_DIR='/var/cache/mikasa-restic')
    return run('restic', *args, env=env, capture_output=capture)


def initialize():
    """One-time migration preserves the existing checkout and interpreter in place."""
    BACKUP_ENV.mkdir(mode=0o700, exist_ok=True)
    password = BACKUP_ENV / 'password'
    if not password.exists():
        with password.open('x') as stream:
            stream.write(secrets.token_urlsafe(48) + '\n')
        password.chmod(0o600)
    if not Path('/var/backups/mikasa-restic/config').exists():
        restic('init')
    RELEASES.mkdir(mode=0o755, exist_ok=True)
    RELEASES.chmod(0o755)
    if not APP.is_symlink():
        with stopped():
            legacy = RELEASES / ('legacy-' + str(int(time.time())))
            stable_venv = Path('/opt/mikasa-venv')
            if stable_venv.exists():
                raise RuntimeError('已有独立解释器目录，请先核对迁移状态')
            (APP / '.venv').rename(stable_venv)
            (APP / '.venv').symlink_to(stable_venv)
            # Preserve the original tree as a recovery archive.
            APP.rename(legacy)
            APP.symlink_to(legacy)
    for name in ('mikasa-backup.service', 'mikasa-backup.timer'):
        shutil.copyfile(Path(__file__).parent / name, '/etc/systemd/system/' + name)
        Path('/etc/systemd/system/' + name).chmod(0o644)
    run('systemctl', 'daemon-reload')
    wait_healthy()
    print('初始化完成；先创建备份、保存恢复密钥，再启用 mikasa-backup.timer。')


def snapshot():
    # Dedicated-account home includes gh auth, dirty repositories, Git objects and worktrees.
    # No gitignore-based exclusions: ignored source and untracked work are also valuable.
    paths = ['/etc/mikasa', '/home/mikasa', str(STATE), str(RELEASES),
             str(APP), '/opt/mikasa-venv', '/opt/hermes', '/opt/hermes-venv', '/opt/python',
             '/etc/systemd/system/mikasa-gateway.service',
             '/etc/systemd/system/mikasa-backup.service', '/etc/systemd/system/mikasa-backup.timer']
    for path in paths:
        if not Path(path).exists():
            raise RuntimeError(f'备份源不存在：{path}')
    result = restic('backup', '--json', '--tag', 'mikasa-vm',
                    '--exclude', '/home/mikasa/.cache',
                    '--exclude', '/home/mikasa/.npm/_cacache',
                    '--exclude', '/home/mikasa/.local/share/Trash',
                    '--exclude', '/var/lib/mikasa/**/.drain_request.json',
                    *paths, capture=True)
    summary = next(json.loads(line) for line in result.stdout.splitlines()
                   if json.loads(line).get('message_type') == 'summary')
    snapshot_id = summary['snapshot_id']
    (BACKUP_ENV / 'last-snapshot').write_text(snapshot_id + '\n')
    print(json.dumps({'snapshot': snapshot_id, 'encrypted': True}))
    return snapshot_id


def validate_release(root):
    marker = root / 'release.json'
    if not marker.exists() and re.fullmatch(r'legacy-[0-9]+', root.name):
        # The first managed deployment is an in-place migration.  Its full
        # runtime tree is deliberately retained as a rollback archive rather
        # than rewritten into a clean source release.
        return {'revision': root.name, 'files': None}
    manifest = json.loads(marker.read_text())
    if set(manifest) != {'revision', 'files'} or not re.fullmatch(r'[a-f0-9]{40}', manifest['revision']):
        raise RuntimeError('非法发布清单')
    for name, expected in manifest['files'].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('发布文件边界不合法')
        if sha(path) != expected:
            raise RuntimeError(f'发布文件校验失败：{name}')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.venv' not in p.parts}
    if actual != set(manifest['files']) | {'release.json'}:
        raise RuntimeError('发布目录包含未登记文件')
    return manifest


def normalize_release_permissions(root):
    """Git archives are extracted under umask 077; the service user needs traversal."""
    for path in Path(root).rglob('*'):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
        elif path.is_file() and not path.is_symlink():
            mode = path.stat().st_mode & 0o111
            path.chmod(0o755 if mode else 0o644)
    Path(root).chmod(0o755)


def unpack(archive, destination):
    with tarfile.open(archive) as source:
        names = set()
        for member in source.getmembers():
            if member.name in names or Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                raise RuntimeError('发布包路径重复或越界')
            names.add(member.name)
            if not (member.isfile() or member.isdir()):
                raise RuntimeError('发布包只能包含普通文件和目录')
        source.extractall(destination, filter='data')
    manifest = validate_release(destination)
    if manifest['files'] is None:
        raise RuntimeError('发布包必须有源码清单')
    return manifest


def point_to(target):
    temporary = APP.with_name('mikasa.next')
    temporary.symlink_to(target)
    temporary.replace(APP)


def skill_roots(saved=None):
    # Only this integration field needs rollback for pre-release-aware versions.
    # Parse using the existing Hermes YAML library and never print whole profiles.
    result = run('/opt/hermes-venv/bin/python', '-B', '-c',
        'import sys,json,pathlib,yaml\n'
        'saved=json.load(sys.stdin)\n'
        'if saved is None:\n'
        ' print(json.dumps({str(p): yaml.safe_load(p.read_text()).get("skills",{}).get("external_dirs",[]) '
        'for p in pathlib.Path("/var/lib/mikasa").glob("*/*/config.yaml")}))\n'
        'else:\n'
        ' for name,roots in saved.items():\n'
        '  p=pathlib.Path(name); d=yaml.safe_load(p.read_text()); '
        'd.setdefault("skills",{})["external_dirs"]=roots; '
        'p.write_text(json.dumps(d,ensure_ascii=False,indent=2))\n',
        input=json.dumps(saved), capture_output=True)
    return json.loads(result.stdout) if saved is None else None


def switch(target):
    if subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode:
        raise RuntimeError('先启动 Gateway；部署/回切要求受管服务正在运行')
    previous = APP.resolve()
    validate_release(target)
    if previous == target:
        raise RuntimeError('目标已经是当前版本')
    switched = False
    saved_roots = {}
    try:
        with stopped():
            snapshot()
            saved_roots = skill_roots()
            try:
                # Explicit rollback may target code predating root tracking.
                skill_roots({p: [str(target / 'skills')] + [r for r in roots if
                    r != '/opt/mikasa/skills' and not re.fullmatch(
                        r'/opt/mikasa-releases/(?:[a-f0-9]{40}|legacy-[0-9]+)/skills', r)]
                    for p, roots in saved_roots.items()})
                point_to(target)
                switched = True
            except Exception:
                skill_roots(saved_roots)
                raise
        wait_healthy()
    except Exception:
        if switched:
            run('systemctl', 'stop', SERVICE)
            point_to(previous)
            skill_roots(saved_roots)
            start_service()
            wait_healthy()
            raise RuntimeError('新版本未通过健康检查，已回切旧代码；运行数据未回滚') from None
        raise
    (BACKUP_ENV / 'previous-release').write_text(str(previous) + '\n')


def deploy(archive):
    RELEASES.mkdir(exist_ok=True)
    RELEASES.chmod(0o755)
    with tempfile.TemporaryDirectory(prefix='.incoming-', dir=RELEASES) as temporary:
        stage = Path(temporary)
        manifest = unpack(archive, stage)
        target = RELEASES / manifest['revision']
        if target.exists():
            validate_release(target)
            if json.loads((target / 'release.json').read_text()) != manifest:
                raise RuntimeError('同一版本目录内容不同')
        else:
            # The Python standard-library app shares a stable interpreter. Hermes is pinned separately.
            (stage / '.venv').symlink_to('/opt/mikasa-venv')
            run('/opt/mikasa-venv/bin/python', '-B', '-c',
                'from mikasa.native import verify_source; from pathlib import Path; verify_source(Path("/opt/hermes"))',
                cwd=stage)
            run('/opt/mikasa-venv/bin/python', '-B', 'scripts/check_docs.py', cwd=stage)
            run('chown', '-R', 'root:mikasa', str(stage))
            normalize_release_permissions(stage)
            stage.chmod(0o755)
            stage.rename(target)
            # TemporaryDirectory tolerates an already-moved staging directory.
    run('runuser', '-u', 'mikasa', '--', '/opt/mikasa-venv/bin/python', '-B', '-m', 'mikasa', '--help',
        cwd=target, capture_output=True)
    switch(target)
    status()


def status():
    marker = APP / 'release.json'
    value = {'release': str(APP.resolve()), 'healthy': healthy(),
             'revision': json.loads(marker.read_text()).get('revision') if marker.exists() else 'legacy',
             'identity_sha256': sha(APP / 'identity.md'),
             'last_snapshot': (BACKUP_ENV / 'last-snapshot').read_text().strip()
                 if (BACKUP_ENV / 'last-snapshot').exists() else None}
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('init')
    commands.add_parser('backup')
    commands.add_parser('check')
    deploy_parser = commands.add_parser('deploy')
    deploy_parser.add_argument('archive', type=Path)
    rollback = commands.add_parser('rollback')
    rollback.add_argument('revision')
    restore = commands.add_parser('restore')
    restore.add_argument('snapshot')
    restore.add_argument('destination', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('在专用 VM 内用 sudo 执行')
    def interrupted(signum, frame):
        raise RuntimeError('维护被中断')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    os.umask(0o077)
    with open('/run/lock/mikasa-vm.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == 'init':
            initialize()
        elif args.command == 'status':
            status()
        elif args.command == 'backup':
            with stopped():
                snapshot()
            wait_healthy()
            restic('forget', '--tag', 'mikasa-vm', '--group-by', 'host,tags',
                   '--keep-daily', '7', '--keep-weekly', '4', '--keep-monthly', '3', '--prune')
        elif args.command == 'check':
            restic('check', '--read-data')
        elif args.command == 'deploy':
            deploy(args.archive.resolve())
        elif args.command == 'rollback':
            target = (RELEASES / args.revision).resolve()
            if target.parent != RELEASES or not target.is_dir():
                raise RuntimeError('只能回切已有版本目录')
            validate_release(target)
            switch(target)
            status()
        elif args.command == 'restore':
            destination = args.destination.absolute()
            if destination.exists() or destination.is_symlink():
                raise RuntimeError('恢复目标必须是尚不存在的新目录')
            destination.mkdir(parents=True, mode=0o700)
            restic('restore', args.snapshot, '--target', str(destination), '--verify')
            print('恢复到独立目录；未启动服务、未覆盖当前数据。绝对符号链接仍指向原位置，离线核对后再切换。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        # Child stderr may contain paths; never print environment or configuration.
        print(f'维护失败：{exc}', file=sys.stderr)
        sys.exit(1)
