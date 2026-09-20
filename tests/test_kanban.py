"""Contract tests against the pinned Hermes SDK, not a copied queue double."""
import concurrent.futures
import contextlib
import json
import fcntl
import shutil
import sqlite3
import time
from pathlib import Path

from mikasa.errors import Conflict, MikasaError
from mikasa.service import Service
from tests.support import BaseTest, REPO


class KanbanTests(BaseTest):
    def board(self):
        return contextlib.closing(sqlite3.connect(self.service.tasks.path))

    def legacy_task(self, task='old-task', state='queued', deps=(), result=None, error=None, actor=None):
        payload = {'kind': 'audit', 'repo': REPO, 'title': task, 'acceptance': 'report', 'depends_on': list(deps)}
        with self.service.store.connect() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (task, 'key-' + task, json.dumps(payload), actor or self.config.owner,
                 self.config.bot, state, json.dumps(result) if result else None, error,
                 'old-token' if state == 'running' else None, 2, 1))
            self.service.store.event(db, task, 'old-evidence', 'tester', {'legacy': task})
        return payload

    def test_migration_preserves_ids_graph_results_actor_and_publication(self):
        self.legacy_task('parent', 'done', result={'summary': 'old output'}, actor='human')
        self.legacy_task('child', deps=['parent', 'parent'])
        self.service.store.reserve_publication('parent')
        self.service.store.publication('parent', 'uncertain', {'note': 'check external service'})
        parent = self.service.tasks.get('parent')
        self.assertEqual(parent['actor'], 'human')
        self.assertEqual(parent['result'], {'summary': 'old output'})
        self.assertNotEqual(parent['native_id'], parent['id'])
        self.assertEqual(self.service.tasks.get('child')['payload']['depends_on'], ['parent'])
        self.assertTrue(any(e['kind'] == 'old-evidence' for e in self.service.tasks.events('parent')))
        with self.service.store.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='tasks'").fetchone())
            self.assertEqual(db.execute('SELECT count(*) FROM legacy_tasks').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT state FROM publications').fetchone()[0], 'uncertain')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE legacy_tasks SET state='queued'")
        restored = Service(self.config, github=self.github)
        self.assertEqual(len(restored.tasks.list()), 2)
        self.assertEqual(restored.run_once()['id'], 'child')
        with self.assertRaises(Conflict):
            restored.store.reserve_publication('parent')

    def test_import_parks_interrupted_cancelled_and_failed_without_retry(self):
        for state in ('running', 'cancelled', 'failed', 'blocked', 'awaiting_review'):
            self.legacy_task(state, state, result={'workspace': '/preserved/' + state}, error='old error')
        tasks = {t['id']: t for t in self.service.tasks.list()}
        self.assertEqual(tasks['running']['state'], 'failed')
        self.assertIn('中断', tasks['running']['error'])
        self.assertEqual(tasks['cancelled']['state'], 'cancelled')
        self.assertEqual(tasks['awaiting_review']['native_status'], 'review')
        self.assertIsNone(self.service.run_once())
        self.assertEqual(tasks['failed']['result']['workspace'], '/preserved/failed')

    def test_crash_between_import_and_cutover_is_idempotent(self):
        self.legacy_task()
        snapshot = self.path / 'before.sqlite3'
        with self.service.store.connect() as db, sqlite3.connect(snapshot) as copy:
            db.backup(copy)
        first = self.service.tasks.get('old-task')
        with sqlite3.connect(snapshot) as before, sqlite3.connect(self.service.store.path) as dest:
            before.backup(dest)
        again = self.service.tasks.get('old-task')
        self.assertEqual(first['native_id'], again['native_id'])
        with self.board() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
        self.assertEqual(len([e for e in self.service.tasks.events('old-task') if e['kind'] == 'old-evidence']), 1)

    def test_cutover_refuses_changed_old_state_and_missing_board(self):
        self.legacy_task()
        snapshot = self.path / 'before.sqlite3'
        with self.service.store.connect() as db, sqlite3.connect(snapshot) as copy:
            db.backup(copy)
        self.service.tasks.list()
        with sqlite3.connect(snapshot) as before, sqlite3.connect(self.service.store.path) as dest:
            before.backup(dest)
            dest.execute("UPDATE tasks SET state='cancelled'")
        with self.assertRaisesRegex(MikasaError, '旧任务发生变化'):
            self.service.tasks.list()
        with self.service.store.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM tasks').fetchone()[0], 'cancelled')
        # A receipts-only restore must not look like an empty new board.
        with self.service.store.connect() as db:
            db.execute('PRAGMA user_version=2')
        with self.board() as db:
            db.execute('DELETE FROM mikasa_import'); db.commit()
        with self.assertRaisesRegex(MikasaError, '数据库缺失'):
            self.service.tasks.list()

    def test_native_dispatch_creates_single_run_and_review_never_respawns(self):
        task = self.submit()
        first = self.service.run_once()
        self.assertEqual(first['native_status'], 'review')
        self.assertIsNone(self.service.run_once())
        with self.board() as db:
            self.assertEqual(db.execute('SELECT status,outcome FROM task_runs').fetchall(), [('review', 'review_requested')])
            self.assertEqual(db.execute('SELECT completion_contract FROM tasks').fetchone()[0], 'local-only')
        self.assertEqual(task['id'], first['id'])

    def test_cancel_parent_does_not_release_children_or_accept_old_run(self):
        parent = self.submit('audit', key='parent')
        child = self.submit('audit', key='child', depends_on=[parent['id']])
        _, token = self.service.tasks.claim(self.config.bot)
        self.service.action(parent['id'], 'cancel', self.config.owner)
        self.assertIsNone(self.service.run_once())
        self.assertEqual(self.service.tasks.get(child['id'])['native_status'], 'todo')
        self.service.action(parent['id'], 'retry', self.config.owner)
        _, new_token = self.service.tasks.claim(self.config.bot)
        self.assertNotEqual(token, new_token)
        with self.assertRaises(Conflict):
            self.service.tasks.finish(parent['id'], token, 'done', {})
        self.service.tasks.finish(parent['id'], new_token, 'done', {})
        self.assertEqual(self.service.run_once()['id'], child['id'])

    def test_cancel_waiting_task_retries_with_parent_gate(self):
        parent = self.submit('audit', key='parent', assignee='human')
        child = self.submit('audit', key='child', depends_on=[parent['id']])
        self.service.action(child['id'], 'cancel', self.config.owner)
        self.assertEqual(self.service.tasks.get(child['id'])['state'], 'cancelled')
        self.service.action(child['id'], 'retry', self.config.owner)
        self.assertEqual(self.service.tasks.get(child['id'])['native_status'], 'todo')
        with self.assertRaises(Conflict):
            self.service.action(child['id'], 'complete', self.config.owner, {'evidence': 'not enough'})
        self.assertIsNone(self.service.run_once())

    def test_concurrent_create_and_claim_use_one_native_task(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            tasks = list(pool.map(lambda _: self.submit('audit'), range(4)))
        self.assertEqual(len({t['id'] for t in tasks}), 1)
        with self.board() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.service.tasks.claim(self.config.bot), range(4)))
        self.assertEqual(sum(c is not None for c in claims), 1)

    def test_heartbeat_and_expiry_fence_execution(self):
        task = self.submit('audit')
        _, token = self.service.tasks.claim(self.config.bot)
        with self.board() as db:
            db.execute('UPDATE tasks SET claim_expires=?', (int(time.time()) + 2,)); db.commit()
        self.service.tasks.call('heartbeat', task=task['id'], token=token)
        with self.board() as db:
            self.assertGreater(db.execute('SELECT claim_expires FROM tasks').fetchone()[0], time.time() + 100)
            db.execute('UPDATE tasks SET claim_expires=0'); db.commit()
        self.assertFalse(self.service.tasks.active(task['id'], token))
        with self.assertRaises(Conflict):
            self.service.tasks.record_execution(task['id'], token, {'phase': 'late'})
        self.service.tasks.recover('runtime')
        self.assertEqual(self.service.tasks.get(task['id'])['state'], 'failed')
        self.assertIsNone(self.service.run_once())

    def test_task_backup_restores_both_authoritative_databases(self):
        from mikasa.backup import backup_tasks
        task = self.submit('audit')
        self.service.run_once()
        self.service.store.reserve_publication(task['id'])
        destination = self.path / 'backup'
        receipt = backup_tasks(self.service, destination)
        self.assertEqual(receipt['scope'], 'tasks-and-receipts')
        self.assertIn('native', receipt['excluded'])
        self.assertEqual((destination / 'kanban/kanban.db').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(MikasaError):
            backup_tasks(self.service, destination)
        restored = self.path / 'restored'
        shutil.copytree(destination, restored)
        self.data['runtime'] = str(restored)
        self.write_config()
        service = Service(self.config, github=self.github)
        self.assertEqual(service.tasks.get(task['id'])['state'], 'done')
        with self.assertRaises(Conflict):
            service.store.reserve_publication(task['id'])

    def test_migration_refuses_live_old_runner_and_preserves_account_spelling(self):
        self.legacy_task()
        with (self.config.runtime / 'runner.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(Conflict, '停止旧 runner'):
                self.service.tasks.list()
        task = self.submit('audit', key='human-owner', assignee=self.config.owner)
        self.assertEqual(task['assignee'], self.config.owner)
        self.assertIsNotNone(self.service.run_once())  # old task, not human-owner
        self.assertIsNone(self.service.run_once())

    def test_native_board_changes_are_visible_without_a_second_task_store(self):
        task = self.submit('audit')
        with self.board() as db:
            db.execute("UPDATE tasks SET title='native edit',status='triage' WHERE id=?", (task['native_id'],))
            db.commit()
        current = self.service.tasks.get(task['id'])
        self.assertEqual(current['payload']['title'], 'native edit')
        self.assertEqual(current['native_status'], 'triage')
        self.assertEqual(current['state'], 'blocked')
        self.assertIsNone(self.service.run_once())

    def test_receipts_cannot_be_paired_with_another_native_board(self):
        self.submit('audit')
        with self.service.store.connect() as db:
            db.execute("UPDATE settings SET value='another-board' WHERE key='kanban_board_id'")
        with self.assertRaisesRegex(MikasaError, '不匹配'):
            self.service.tasks.list()
