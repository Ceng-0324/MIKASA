"""Task API adapter; Hermes owns the board, graph, claims and run history."""
import json
import threading
from contextlib import closing, contextmanager
import sqlite3
from pathlib import Path

from .errors import Conflict, MikasaError, NotFound
from .native import verify_source
from .process import clean_env, run


class Kanban:
    def __init__(self, config):
        self.config = config
        self.home = config.runtime / 'kanban'
        self.path = self.home / 'kanban.db'
        self._prepared = False
        settings = config.data.get('worker', {})
        self.source = (config.root / settings.get('hermes_source', 'runtime/cache/hermes-source')).resolve()
        self.python = Path(settings.get('native_python', config.root / 'runtime/cache/hermes-venv/bin/python'))
        if not self.python.is_absolute():
            self.python = config.root / self.python

    def diagnostics(self):
        return {'backend': 'hermes_kanban', 'python_present': self.python.is_file(),
                'source_present': (self.source / 'hermes_cli/kanban_db.py').is_file(),
                'connection': 'not_checked', 'migration': 'not_run'}

    def call(self, operation, **values):
        if not self.python.is_file():
            raise MikasaError('任务功能需要安装固定 Hermes 环境；参见 workers/hermes/README.md')
        for path in (self.home, self.path, self.home / 'adapter.lock', self.home / 'config.yaml', self.home / 'workspace'):
            if path.is_symlink():
                raise MikasaError('Kanban 文件和目录不能为外部链接')
        if not self._prepared:
            verify_source(self.source)
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._prepared = True
        env = clean_env({'HERMES_HOME': str(self.home), 'HERMES_KANBAN_HOME': str(self.home),
                         'HERMES_KANBAN_DB': str(self.path), 'MIKASA_HERMES_SOURCE': str(self.source),
                         'HERMES_ENABLE_PROJECT_PLUGINS': '0'})
        request = {'operation': operation, 'values': values, 'runtime': str(self.config.runtime),
                   'bot': self.config.bot,
                   'accounts': [self.config.owner, self.config.bot, *self.config.data.get('members', [])]}
        reply = run([str(self.python.absolute()), str(self.config.root / 'workers/hermes/kanban_adapter.py')],
                    cwd=self.home, env=env, stdin=json.dumps(request), timeout=60, limit=16_000_000)
        try:
            data = json.loads(reply['stdout'])
        except ValueError:
            raise MikasaError('Hermes Kanban 响应无效；原数据保留') from None
        if 'error' in data:
            kind = {'Conflict': Conflict, 'NotFound': NotFound}.get(data['error'], MikasaError)
            raise kind(data.get('message', 'Hermes Kanban 操作失败；原数据保留'))
        if reply['code']:
            raise MikasaError('Hermes Kanban 执行失败；原数据保留')
        return data['result']

    def create(self, payload, actor, assignee, key):
        return self.call('create', payload=payload, actor=actor, assignee=assignee, key=key)

    def get(self, task):
        return self.call('get', task=task)

    def list(self):
        return self.call('list')

    def events(self, task):
        return self.call('events', task=task)

    def claim(self, bot):
        return self.call('dispatch', bot=bot)

    def finish(self, task, token, state, result=None, error=None):
        return self.call('finish', task=task, token=token, state=state, result=result, error=error)

    def record_execution(self, task, token, data):
        return self.call('progress', task=task, token=token, data=data)

    def transition(self, task, action, actor, **data):
        return self.call('transition', task=task, action=action, actor=actor, **data)

    def recover(self, actor):
        """Caller holds runner.lock; no live Mikasa runner may be recovered."""
        return self.call('recover', actor=actor)

    def active(self, task, token):
        # A polling read must not start an SDK process every 50 ms. No local
        # task cache or copied status: inspect the authoritative native claim.
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            return bool(db.execute('''SELECT 1 FROM tasks t JOIN mikasa_ids m ON m.native_id=t.id
                WHERE m.external_id=? AND t.status='running' AND t.claim_lock=? AND t.claim_expires >= unixepoch()''', (task, token)).fetchone())

    @contextmanager
    def lease(self, task, token):
        stopped, lost = threading.Event(), threading.Event()
        def renew():
            while not stopped.wait(30):
                try:
                    self.call('heartbeat', task=task, token=token)
                except MikasaError:
                    lost.set()
                    return
        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            yield lambda: lost.is_set() or not self.active(task, token)
        finally:
            stopped.set()
            thread.join()
