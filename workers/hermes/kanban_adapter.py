"""Pinned Hermes Kanban integration. No model, credentials or network required.

Only migration writes native lifecycle columns directly. Live lifecycle changes
use upstream verbs/dispatcher; namespaced events carry Mikasa API evidence.
"""
import fcntl
import hashlib
import json
import os
import sqlite3
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect_closing, write_txn
from hermes_cli.kanban_db_dispatch import dispatch_once
from mikasa.errors import Conflict, MikasaError, NotFound


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Board:
    def __init__(self, conn, request):
        self.db = conn
        self.runtime = Path(request['runtime'])
        self.bot = request['bot']
        self.accounts = {a.lower(): a for a in request.get('accounts', [])}

    def assignee(self, value):
        return 'default' if value == self.bot else 'human-' + value

    def native_id(self, external):
        row = self.db.execute('SELECT native_id FROM mikasa_ids WHERE external_id=?', (external,)).fetchone()
        if row is None:
            raise NotFound('任务不存在')
        return row[0]

    def event(self, task, kind, actor, data, *, run_id=None, created=None):
        self.db.execute('''INSERT INTO task_events(task_id,run_id,kind,payload,created_at)
            VALUES(?,?,'mikasa',?,?)''',
            (task, run_id, encoded({'kind': kind, 'actor': actor, 'data': data}), int(time.time()) if created is None else created))

    def migrate(self):
        # The adapter lock serializes retries. Native import commits BEFORE the
        # legacy queue is renamed: a crash can resume via the durable marker.
        self.db.execute('''CREATE TABLE IF NOT EXISTS mikasa_ids (
            external_id TEXT PRIMARY KEY, native_id TEXT UNIQUE NOT NULL,
            request_key TEXT UNIQUE NOT NULL, request_json TEXT NOT NULL)''')
        self.db.execute('CREATE TABLE IF NOT EXISTS mikasa_import (version INTEGER PRIMARY KEY, digest TEXT NOT NULL, board_id TEXT NOT NULL)')
        legacy = self.runtime / 'mikasa.sqlite3'
        with sqlite3.connect(legacy) as old:
            old.row_factory = sqlite3.Row
            version = old.execute('PRAGMA user_version').fetchone()[0]
            if version == 2:
                marker = self.db.execute('SELECT board_id FROM mikasa_import WHERE version=1').fetchone()
                binding = old.execute("SELECT value FROM settings WHERE key='kanban_board_id'").fetchone()
                if not marker or not binding or marker[0] != binding[0]:
                    raise MikasaError('Kanban 数据库缺失或与旧档案不匹配；拒绝空队列启动')
                return
            if version != 1:
                raise MikasaError('旧运行数据库版本不兼容')
            with (self.runtime / 'runner.lock').open('a') as runner:
                try:
                    fcntl.flock(runner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Conflict('旧任务仍在运行；停止旧 runner 后再迁移') from None
                # Hold the old write lock until cutover. Old binaries may not append
                # tasks between reading the source and retiring its queue.
                old.execute('BEGIN IMMEDIATE')
                rows = old.execute('SELECT * FROM tasks ORDER BY created,id').fetchall()
                archive = {'tasks': [dict(r) for r in rows], 'events': [dict(r) for r in old.execute('SELECT * FROM events WHERE task_id IS NOT NULL ORDER BY seq')]}
                digest = hashlib.sha256(encoded(archive).encode()).hexdigest()
                if not self.db.execute('SELECT 1 FROM mikasa_import WHERE version=1').fetchone():
                    with write_txn(self.db):
                        for row in rows:
                            payload = json.loads(row['payload'])
                            native = self.create(payload, row['actor'], row['assignee'], row['request_key'],
                                                 external=row['id'])
                            state = {'queued': 'todo', 'running': 'blocked', 'failed': 'blocked',
                                     'blocked': 'blocked', 'cancelled': 'blocked',
                                     'awaiting_review': 'review', 'done': 'done'}[row['state']]
                            error = ('执行进程中断；检查保留的工作区后显式重试'
                                     if row['state'] == 'running' else row['error'])
                            self.db.execute('''UPDATE tasks SET status=?,result=?,created_at=?,completed_at=? WHERE id=?''',
                                (state, encoded({'result': json.loads(row['result']) if row['result'] else None,
                                                 'error': error}), int(row['created']),
                                 int(row['updated']) if state == 'done' else None, native))
                            for event in old.execute('SELECT * FROM events WHERE task_id=? ORDER BY seq', (row['id'],)):
                                self.event(native, event['kind'], event['actor'], json.loads(event['data']),
                                           created=int(event['created']))
                            if state == 'blocked':
                                kb._append_event(self.db, native, 'blocked', {'reason': error or row['state'], 'kind': 'needs_input'})
                                self.event(native, 'interrupted' if row['state'] == 'running' else row['state'],
                                           'migration', {})
                        # Links are added only after all IDs exist (old row ordering
                        # is not guaranteed to be topological).
                        for row in rows:
                            for parent in json.loads(row['payload']).get('depends_on', []):
                                self.db.execute('INSERT OR IGNORE INTO task_links(parent_id,child_id) VALUES(?,?)',
                                                (self.native_id(parent), self.native_id(row['id'])))
                        self.db.execute('INSERT INTO mikasa_import VALUES(1,?,?)', (digest, secrets.token_hex(16)))
                else:
                    # Interrupted cutover: refuse new old-binary writes instead of
                    # silently discarding them. Original tables remain untouched.
                    if digest != self.db.execute('SELECT digest FROM mikasa_import WHERE version=1').fetchone()[0]:
                        raise MikasaError('迁移中旧任务发生变化；停止旧 runner 后核对原档案')
                old.execute('ALTER TABLE tasks RENAME TO legacy_tasks')
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    old.execute(f'''CREATE TRIGGER legacy_tasks_no_{operation.lower()} BEFORE {operation} ON legacy_tasks
                        BEGIN SELECT RAISE(ABORT, 'legacy task archive is read-only'); END''')
                board_id = self.db.execute('SELECT board_id FROM mikasa_import WHERE version=1').fetchone()[0]
                old.execute("INSERT OR REPLACE INTO settings VALUES('kanban_board_id',?)", (board_id,))
                old.execute('PRAGMA user_version=2')
        kb.recompute_ready(self.db)

    def create(self, payload, actor, assignee, key, external=None):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise MikasaError('request_key 必须为 1–200 字符')
        request = encoded({'payload': payload, 'actor': actor})
        row = self.db.execute('SELECT native_id,request_json FROM mikasa_ids WHERE request_key=?', (key,)).fetchone()
        if row:
            if row['request_json'] != request:
                raise Conflict('幂等键已用于另一请求')
            return row['native_id'] if external else self.view(row['native_id'])
        parents = [] if external else [self.native_id(p) for p in payload.get('depends_on', [])]
        with write_txn(self.db, allow_nested=True):
            native = kb.create_task(self.db, title=payload['title'], body=encoded(payload),
                assignee=self.assignee(assignee), created_by=actor, parents=parents,
                workspace_kind='dir', workspace_path=str(self.runtime / 'kanban' / 'workspace'),
                idempotency_key=key, max_retries=1, completion_contract='local-only')
            self.db.execute('INSERT INTO mikasa_ids VALUES(?,?,?,?)', (external or native, native, key, request))
        return native if external else self.view(native)

    def view(self, native):
        task = kb.get_task(self.db, native)
        if task is None:
            raise NotFound('任务不存在')
        binding = self.db.execute('SELECT * FROM mikasa_ids WHERE native_id=?', (native,)).fetchone()
        payload = json.loads(task.body)
        payload['title'] = task.title
        # Native links are authoritative, including changes made with Hermes.
        payload['depends_on'] = [r[0] for r in self.db.execute('''SELECT m.external_id FROM task_links l
            JOIN mikasa_ids m ON m.native_id=l.parent_id WHERE l.child_id=? ORDER BY l.rowid''', (native,))]
        result = json.loads(task.result) if task.result else {}
        state = {'ready': 'queued', 'todo': 'queued', 'scheduled': 'blocked', 'triage': 'blocked',
                 'review': 'awaiting_review', 'archived': 'cancelled'}.get(task.status, task.status)
        last = self.db.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='mikasa' ORDER BY id DESC LIMIT 1", (native,)).fetchone()
        marker = json.loads(last[0])['kind'] if last else None
        if task.status in {'blocked', 'triage', 'scheduled'}:
            if marker in {'failed', 'interrupted'}:
                state = 'failed'
            elif marker in {'cancel', 'cancelled'}:
                state = 'cancelled'
        stamp = self.db.execute('SELECT MAX(created_at) FROM task_events WHERE task_id=?', (native,)).fetchone()[0]
        return {'id': binding['external_id'], 'native_id': native, 'native_status': task.status,
                'request_key': binding['request_key'], 'payload': payload, 'actor': task.created_by,
                'assignee': self.bot if task.assignee == 'default' else self.accounts.get((task.assignee or '').removeprefix('human-'), (task.assignee or '').removeprefix('human-')),
                'state': state, 'result': result.get('result'), 'error': result.get('error'),
                'created': task.created_at, 'updated': stamp or task.created_at}

    def owned(self, native, token):
        task = kb.get_task(self.db, native)
        if task.status != 'running' or task.claim_lock != token or (task.claim_expires or 0) < int(time.time()):
            raise Conflict('执行租约已失效，拒绝旧进程写入')
        return task

    def finish(self, task, token, state, result=None, error=None, *, recovering=False):
        native = self.native_id(task)
        current = kb.get_task(self.db, native) if recovering else self.owned(native, token)
        # Write-ahead delivery: interrupted transition leaves a RUNNING task,
        # never a false completed task. Recovery parks it, preserving evidence.
        with write_txn(self.db):
            if not self.db.execute("UPDATE tasks SET result=? WHERE id=? AND status='running' AND claim_lock=?",
                (encoded({'result': result, 'error': error}), native, token)).rowcount:
                raise Conflict('执行租约已失效')
        if state == 'done':
            ok = kb.complete_task(self.db, native, result=encoded({'result': result, 'error': error}),
                                  expected_run_id=current.current_run_id)
        elif state == 'awaiting_review':
            ok = kb.request_review(self.db, native, summary=(result or {}).get('summary'),
                                   expected_run_id=current.current_run_id)
        elif state in {'blocked', 'failed'}:
            ok = kb.block_task(self.db, native, reason=error or (result or {}).get('summary') or '最终验收未完成',
                               kind='needs_input', expected_run_id=current.current_run_id)
        else:
            raise MikasaError('非法任务结束状态')
        if not ok:
            raise Conflict('Hermes 拒绝结束当前任务')
        with write_txn(self.db):
            self.event(native, state, 'runtime', {'error': error}, run_id=current.current_run_id)

    def transition(self, task, action, actor, assignee=None, evidence=None):
        native = self.native_id(task)
        current = kb.get_task(self.db, native)
        state = self.view(native)['state']
        ok = False
        if action == 'cancel' and state not in {'done', 'cancelled'}:
            if current.status == 'review':
                kb.reopen_review_task(self.db, native)
                current = kb.get_task(self.db, native)
            if current.status in {'running', 'ready'}:
                ok = kb.block_task(self.db, native, reason='用户取消；等待显式重试', kind='needs_input',
                                   expected_run_id=current.current_run_id)
            elif current.status == 'todo':
                ok = kb.schedule_task(self.db, native, reason='用户取消；等待显式重试')
            else:
                ok = current.status in {'blocked', 'triage', 'scheduled'}
        elif action == 'retry' and state in {'failed', 'blocked', 'cancelled'}:
            ok = (kb.specify_triage_task(self.db, native, author=actor) if current.status == 'triage'
                  else kb.unblock_task(self.db, native))
        elif action == 'assign' and state in {'queued', 'blocked'} and assignee:
            ok = kb.assign_task(self.db, native, self.assignee(assignee))
            if current.status in {'blocked', 'scheduled'}:
                ok = kb.unblock_task(self.db, native) and ok
        elif action == 'complete' and state in {'queued', 'awaiting_review', 'blocked'} and evidence:
            kb.recompute_ready(self.db)
            ok = kb.complete_task(self.db, native, result=current.result, summary=evidence)
        if not ok:
            raise Conflict('当前状态或依赖不允许此操作，或缺少交付证据')
        with write_txn(self.db):
            self.event(native, action, actor, {'assignee': assignee, 'evidence': evidence})
        return self.view(native)

    def dispatch(self, bot):
        if bot != self.bot:
            raise MikasaError('执行账号与配置不匹配')
        with sqlite3.connect(self.runtime / 'mikasa.sqlite3') as old:
            paused = old.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
        if paused and paused[0] == 'true':
            return None
        claimed = []
        def handoff(task, workspace, *, board=None):
            # This spawn extension hands the native lease to the host's
            # synchronous engineering executor. No extra queue or second claim.
            if not self.db.execute('SELECT 1 FROM mikasa_ids WHERE native_id=?', (task.id,)).fetchone():
                raise ValueError('unbound task')
            claimed.append([self.view(task.id), task.claim_lock])
            return None
        dispatch_once(self.db, spawn_fn=handoff, ttl_seconds=120,
                         max_spawn=1, max_in_progress=1, failure_limit=1, reconcile_orphans=False)
        return claimed[0] if claimed else None

    def execute(self, operation, values):
        if operation == 'prepare':
            return None
        if operation == 'create':
            return self.create(**values)
        if operation == 'list':
            return [self.view(r[0]) for r in self.db.execute('''SELECT t.id FROM tasks t
                JOIN mikasa_ids m ON m.native_id=t.id ORDER BY t.created_at DESC,t.rowid DESC LIMIT 500''')]
        if operation == 'dispatch':
            return self.dispatch(**values)
        if operation == 'recover':
            tasks = self.db.execute("SELECT t.id,t.claim_lock,m.external_id FROM tasks t JOIN mikasa_ids m ON m.native_id=t.id WHERE t.status='running'").fetchall()
            for task in tasks:
                self.finish(task['external_id'], task['claim_lock'], 'failed',
                            result=self.view(task['id'])['result'], error='执行进程中断；检查保留的工作区后显式重试', recovering=True)
                with write_txn(self.db):
                    self.event(task['id'], 'interrupted', values['actor'], {})
            return len(tasks)
        native = self.native_id(values['task'])
        if operation == 'get':
            return self.view(native)
        if operation == 'events':
            return [{'seq': e.id, 'task_id': values['task'], 'created': e.created_at,
                     **(e.payload if e.kind == 'mikasa' else {'kind': e.kind, 'actor': 'hermes', 'data': e.payload or {}})}
                    for e in kb.list_events(self.db, native)]
        if operation == 'heartbeat':
            self.owned(native, values['token'])
            if not kb.heartbeat_claim(self.db, native, ttl_seconds=120, claimer=values['token']):
                raise Conflict('执行租约已失效')
            return None
        if operation == 'progress':
            with write_txn(self.db):
                current = self.owned(native, values['token'])
                self.event(native, 'execution', 'runtime', values['data'], run_id=current.current_run_id)
            return None
        if operation == 'finish':
            return self.finish(**values)
        if operation == 'transition':
            return self.transition(**values)
        raise MikasaError('不支持的 Kanban 操作')


def main():
    os.umask(0o077)
    request = json.load(sys.stdin)
    home = Path(os.environ['HERMES_HOME'])
    # Never load personal profiles/plugins/model settings into this control plane.
    if (home / '.env').exists() or (home / '.env').is_symlink():
        raise MikasaError('Kanban home 不允许额外 .env 注入')
    with (home / 'adapter.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        (home / 'workspace').mkdir(exist_ok=True)
        (home / 'config.yaml').write_text(encoded({'kanban': {'review_dispatch': False}, 'plugins': {'enabled': []}}))
        with connect_closing() as conn:
            board = Board(conn, request)
            board.migrate()
            result = board.execute(request['operation'], request['values'])
    print(encoded({'result': result}))


if __name__ == '__main__':
    try:
        main()
    except MikasaError as exc:
        print(encoded({'error': type(exc).__name__, 'message': str(exc)}))
        sys.exit(1)
    except Exception as exc:
        # Exception bodies can include task contents or local paths.
        print(encoded({'error': type(exc).__name__, 'message': 'Hermes Kanban 操作失败（' + type(exc).__name__ + '）；原数据保留'}))
        sys.exit(1)
