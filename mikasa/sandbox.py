"""Host-owned snapshot boundary for native Hermes file and terminal tools."""
import hashlib
import json
import os
import stat
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .errors import MikasaError
from .process import git
from .workspace import PROTECTED, sensitive

IMAGE = 'python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9'
MAX_FILES = 5000
MAX_BYTES = 50_000_000
MAX_FILE_BYTES = 1_000_000


class Snapshot:
    """Only regular text blobs enter the sandbox; only validated deltas leave it."""
    def __init__(self, workspace, kind, cancelled=lambda: False):
        self.workspace, self.kind, self.cancelled = workspace, kind, cancelled
        self.directory = None
        self.original = {}
        self.modes = {}
        self.coverage = {}
        self.omitted = []

    def __enter__(self):
        w = self.workspace
        self.directory = Path(tempfile.mkdtemp(prefix='native-', dir=w.path.parent))
        self.path = self.directory
        try:
            # Repair invocations start from the already staged implementation.
            self.revision = git(['write-tree'], w.path) if self.kind == 'implement' else w.head
            entries = git(['ls-tree', '-rz', self.revision], w.path, strip=False).split('\0')
            total = 0
            for entry in filter(None, entries):
                if self.cancelled():
                    raise MikasaError('任务已取消')
                meta, name = entry.split('\t', 1)
                mode, _, oid = meta.split()
                parts = PurePosixPath(name).parts
                if (mode not in {'100644', '100755'} or sensitive(name) or set(parts) & PROTECTED
                        or '\\' in name or str(PurePosixPath(name)) != name or '..' in parts):
                    self.omitted.append(name)
                    continue
                size = int(git(['cat-file', '-s', oid], w.path))
                if size > MAX_FILE_BYTES:
                    self.omitted.append(name)
                    continue
                try:
                    content = git(['cat-file', 'blob', oid], w.path, strip=False, decode_errors='strict')
                except UnicodeError:
                    self.omitted.append(name)
                    continue
                if '\0' in content:
                    self.omitted.append(name)
                    continue
                total += size
                if total > MAX_BYTES or len(self.original) >= MAX_FILES:
                    raise MikasaError('原生工作区快照超过文件或大小预算')
                target = self.path / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content.encode())
                target.chmod(0o755 if mode == '100755' else 0o644)
                self.original[name] = content
                self.modes[name] = stat.S_IMODE(target.stat().st_mode)
            return self
        except BaseException:
            shutil.rmtree(self.directory)
            raise

    def __exit__(self, *args):
        shutil.rmtree(self.directory)

    def terminal_config(self, image=IMAGE):
        if any(c in str(self.path) for c in ':,\n'):
            raise MikasaError('容器挂载路径包含不支持的字符')
        return {'backend': 'docker', 'cwd': '/workspace', 'docker_image': image,
                'docker_volumes': [str(self.path) + ':/workspace:' + ('rw' if self.kind == 'implement' else 'ro')],
                'docker_network': False, 'container_persistent': False,
                'docker_persist_across_processes': False, 'docker_orphan_reaper': False,
                'container_cpu': 2, 'container_memory': 1024, 'container_disk': 0,
                'docker_run_as_host_user': True, 'docker_extra_args': ['--read-only'],
                'docker_forward_env': [], 'env_passthrough': [],
                'docker_env': {'PYTHONDONTWRITEBYTECODE': '1'}}

    def changes(self):
        current, total, entries = {}, 0, 0
        # Never follow a model-created symlink, FIFO, socket or hardlink on the host.
        for directory, dirs, files in os.walk(self.path, followlinks=False):
            for name in dirs + files:
                entries += 1
                if entries > MAX_FILES * 2:
                    raise MikasaError('原生工作区目录项超过预算')
                path = Path(directory) / name
                info = path.lstat()
                relative = path.relative_to(self.path).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES:
                    raise MikasaError('原生工作区包含链接、特殊文件或超大文件')
                total += info.st_size
                if len(current) >= MAX_FILES or total > MAX_BYTES:
                    raise MikasaError('原生工作区产物超过预算')
                # O_NOFOLLOW closes the final-component symlink race. Import occurs
                # after native teardown; interactive checkpoints hold the tool lock.
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise MikasaError('原生工作区文件类型发生变化')
                    raw = stream.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES or b'\0' in raw:
                    raise MikasaError('原生工作区包含超大或二进制产物')
                try:
                    current[relative] = raw.decode('utf-8')
                except UnicodeError:
                    raise MikasaError('原生工作区产物必须是 UTF-8 文本') from None
                if relative in self.modes and stat.S_IMODE(info.st_mode) != self.modes[relative]:
                    raise MikasaError('原生工作区不支持修改文件权限')
        delta = [{'path': name, 'content': current.get(name)} for name in sorted(set(current) | set(self.original))
                 if current.get(name) != self.original.get(name)]
        if any(change['path'] in self.omitted for change in delta):
            raise MikasaError('拒绝覆盖未导出的仓库文件')
        if self.kind != 'implement' and delta:
            raise MikasaError('只读原生工作区发生变化')
        return delta

    def apply(self):
        delta = self.changes()
        if delta:
            self.workspace.apply(delta, cancelled=self.cancelled)
            for change in delta:
                name, content = change['path'], change['content']
                if content is None:
                    self.original.pop(name, None)
                    self.modes.pop(name, None)
                else:
                    self.original[name] = content
                    self.modes[name] = stat.S_IMODE((self.path / name).stat().st_mode)
        return delta

    def observe_read(self, path, result):
        """Verify native line-numbered output against the pinned host snapshot.

        A tail page, redacted output, error, terminal cat, or model claim never
        counts as complete review evidence.
        """
        if not isinstance(path, str) or self.kind == 'implement':
            return {}
        name = path.removeprefix('/workspace/')
        if name not in self.original:
            return {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                return {}
        if not isinstance(result, dict) or result.get('error'):
            return {}
        content = self.original[name]
        lines = content.splitlines()
        covered = self.coverage.setdefault(name, set())
        for line in str(result.get('content', '')).splitlines():
            number, sep, text = line.partition('|')
            if sep and number.strip().isdigit():
                index = int(number.strip()) - 1
                if 0 <= index < len(lines) and text == lines[index]:
                    covered.add(index)
        return {'path': name, 'revision': self.workspace.head,
                'sha256': hashlib.sha256(content.encode()).hexdigest(),
                'complete': len(covered) == len(lines) and (bool(lines) or result.get('total_lines') == 0)}
