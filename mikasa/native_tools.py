"""Task policy and evidence over Hermes' native tools; no file/terminal implementation."""
import uuid
from contextlib import contextmanager

from .agent_tools import ToolChannel, WRITE_TOOLS, run_checks
from .errors import MikasaError
from .process import run
from .sandbox import Snapshot

NATIVE_TOOLS = ['read_file', 'write_file', 'patch', 'search_files', 'terminal']


class NativeToolSession(ToolChannel):
    def __init__(self, workspace, kind, cancelled, *, progress=None):
        super().__init__(workspace, kind, cancelled, progress=progress)
        self.schemas = [WRITE_TOOLS[-1]] if kind == 'implement' else []
        self.native_id = 'mikasa-' + uuid.uuid4().hex
        self.snapshot = Snapshot(workspace, kind, self.is_cancelled)
        self.native_grants = [n for n in NATIVE_TOOLS if kind == 'implement' or n not in {'write_file', 'patch'}]
        self.native_grants += ['memory', 'skills_list', 'skill_view']
        self.native_grants += [s['name'] for s in self.schemas]

    def __enter__(self):
        self.snapshot.__enter__()
        # Read-only tasks still require a trusted evidence channel.
        import socket
        import threading
        self.parent, self.child = socket.socketpair()
        self.thread = threading.Thread(target=self.serve, name='mikasa-native-evidence', daemon=True)
        self.thread.start()
        return self

    def docker(self, args):
        result = run(['docker', *args], cwd=self.workspace.config.root, timeout=30, limit=100000)
        if result['code']:
            raise MikasaError('原生工程容器生命周期操作失败')
        return result['stdout']

    def containers(self):
        return self.docker(['ps', '-aq', '--filter', 'label=hermes-task-id=' + self.native_id]).split()

    @contextmanager
    def frozen(self):
        ids = self.containers()
        paused = []
        try:
            for cid in ids:
                self.docker(['pause', cid])
                paused.append(cid)
            yield
        finally:
            for cid in paused:
                self.docker(['unpause', cid])

    def finish(self):
        # The SDK normally drains native teardown before returning. Remove any
        # remaining task containers before importing model-controlled files.
        for cid in self.containers():
            self.docker(['rm', '-f', cid])
        if self.kind == 'implement':
            self.applied = bool(self.snapshot.apply()) or self.applied
        else:
            self.snapshot.changes()

    def __exit__(self, *args):
        super().__exit__(*args)
        # A failed removal must retain the mounted snapshot for recovery. Do not
        # delete files while a surviving container could still be changing them.
        for cid in self.containers():
            self.docker(['rm', '-f', cid])
        self.snapshot.__exit__(*args)

    def call(self, name, args):
        if self.is_cancelled() or self.fatal or len(self.events) >= 128:
            self.fatal = '原生工具已取消、超出预算或验证失败'
            return {'error': self.fatal}
        if name == '_native_event':
            tool = args.get('tool')
            if tool in {'tool_search', 'tool_call', 'tool_describe'}:
                return {'ok': True}  # Hermes emits a separate underlying tool event.
            if tool not in self.native_grants:
                return {'error': '未知原生工具'}
            if tool == 'mikasa_run_checks':
                return {'ok': True}  # The host records this business operation itself.
            event = {'tool': tool, 'ok': args.get('status') == 'ok'}
            if tool == 'read_file' and event['ok']:
                event.update(self.snapshot.observe_read(args.get('path'), args.get('result')))
            self.events.append(event)
            if self.progress:
                self.progress({'phase': 'tool', 'status': 'completed', **event})
            return {'ok': True}
        if name != 'mikasa_run_checks' or self.kind != 'implement' or args != {}:
            return {'error': '工具未授权'}
        try:
            if self.progress:
                self.progress({'phase': 'tool', 'status': 'started', 'tool': name})
            with self.frozen():
                self.applied = bool(self.snapshot.apply()) or self.applied
                checks = run_checks(self.workspace, self.is_cancelled)
            event = {'tool': name, 'ok': True, 'checks': [{'command': c['command'], 'code': c['code']} for c in checks]}
            self.events.append(event)
            if self.progress:
                self.progress({'phase': 'tool', 'status': 'completed', **event})
            return {'checks': checks, 'passed': bool(checks) and all(c['code'] == 0 for c in checks)}
        except (MikasaError, OSError, ValueError):
            self.fatal = '原生工作区导入或宿主检查失败；拒绝交付'
            return {'error': self.fatal}
