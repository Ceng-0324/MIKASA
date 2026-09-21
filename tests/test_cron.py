"""Real pinned Cron tick/script/occurrence contracts, with no model or network."""
import fcntl
import json
import os
import sqlite3
from datetime import datetime
from unittest.mock import patch

from mikasa.config import Config
from mikasa.backup import backup_state, restore_state
from mikasa.cron import Cron
from mikasa.errors import Conflict, MikasaError
from mikasa.process import clean_env, run
from mikasa.service import Service
from tests.support import BaseTest, REPO, ROOT


class CronTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.config.data['schedules'] = {'audit_interval_seconds': 90}
        self.home = self.config.runtime / 'scheduler'

    def sdk(self, code, **values):
        env = clean_env({'HERMES_HOME': str(self.home)})
        result = run([str(self.service.tasks.python), '-c',
                      'import sys,json; sys.path.insert(0,sys.argv[1]); values=json.loads(sys.argv[2]); ' + code,
                      str(self.service.tasks.source), json.dumps(values)], cwd=self.home, env=env)
        self.assertEqual(result['code'], 0, result['stderr'])
        return json.loads(result['stdout']) if result['stdout'].strip() else None

    def due(self, job):
        return self.sdk("from cron.jobs import update_job; from datetime import datetime,timezone,timedelta; "
                        "print(json.dumps(update_job(values['id'], {'next_run_at':(datetime.now(timezone.utc)-timedelta(seconds=3)).isoformat()})))",
                        id=job['id'])

    def update(self, job, **fields):
        return self.sdk("from cron.jobs import update_job; print(json.dumps(update_job(values['id'], values['fields'])))",
                        id=job['id'], fields=fields)

    def executions(self, job):
        return self.sdk("from cron.executions import list_executions; print(json.dumps(list_executions(job_id=values['id'])))",
                        id=job['id'])

    def test_native_due_tick_restart_and_one_board_handoff(self):
        initial = self.service.schedule()
        job = initial['job']
        self.assertEqual(initial['executed'], 0)
        self.assertAlmostEqual((datetime.fromisoformat(job['next_run_at']) - datetime.fromisoformat(job['created_at'])).total_seconds(), 90, delta=3)
        restarted = Service(self.config, github=self.github)
        self.assertEqual(restarted.schedule()['job']['next_run_at'], job['next_run_at'])
        self.assertEqual(restarted.tasks.list(), [])
        self.due(job)
        self.assertEqual(restarted.schedule()['executed'], 1)
        task, = restarted.tasks.list()
        execution, = self.executions(job)
        self.assertEqual(execution['status'], 'completed')
        self.assertIn(execution['scheduled_instant'], task['request_key'])
        self.assertEqual(task['native_status'], 'ready')
        self.assertEqual(restarted.run_once()['id'], task['id'])
        self.assertEqual(restarted.tasks.get(task['id'])['state'], 'done')
        self.assertIsNone(restarted.run_once())
        # Native lifecycle hooks may initialize an empty SessionDB, but the
        # no_agent job must not create a model conversation.
        if (self.home / 'state.db').exists():
            with sqlite3.connect(self.home / 'state.db') as db:
                self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0], 0)
        self.assertEqual(self.github.writes, [])

    def test_restored_cron_preserves_occurrence_and_uses_new_runtime(self):
        job = self.service.schedule()['job']
        self.due(job)
        current = self.service.schedule()['job']
        previous = self.executions(job)
        backup = self.path / 'backup'
        backup_state(self.service, backup)
        restored = self.path / 'restored'
        restore_state(self.config, backup, restored)
        self.data.update(runtime=str(restored), schedules={'audit_interval_seconds': 90})
        self.write_config()
        self.home = restored / 'scheduler'
        self.service = Service(self.config, github=self.github)
        self.assertEqual(self.service.schedule()['job']['next_run_at'], current['next_run_at'])
        self.assertEqual(self.executions(job), previous)
        self.assertEqual(len(self.service.tasks.list()), 1)
        self.service.run_once()
        self.due(job)
        self.assertEqual(self.service.schedule()['executed'], 1)
        self.assertEqual(len(self.service.tasks.list()), 2)
        integration = json.loads((self.home / 'integration.json').read_text())
        self.assertEqual(integration['runtime'], str(restored))

    def test_active_audit_suppresses_later_occurrence_and_replay_is_idempotent(self):
        job = self.service.schedule()['job']
        self.due(job)
        self.service.schedule()
        first, = self.service.tasks.list()
        self.due(job)
        self.service.schedule()
        self.assertEqual([t['id'] for t in self.service.tasks.list()], [first['id']])
        self.service.run_once()
        # Crash after enqueue but before Cron acknowledgement: replay the same
        # native occurrence even after the submitted task has already completed.
        replay = self.service.tasks.call('audit_occurrence', repos=[REPO], actor=self.config.owner,
                                         key=first['request_key'].rsplit(':' + REPO, 1)[0])
        self.assertEqual(replay[0]['id'], first['id'])
        self.due(job)
        self.service.schedule()
        self.assertEqual(len(self.service.tasks.list()), 2)

    def test_host_pause_and_native_pause_keep_due_state(self):
        job = self.service.schedule()['job']
        due = self.due(job)
        self.service.store.pause(True, self.config.owner)
        self.assertEqual(self.service.schedule()['job']['next_run_at'], due['next_run_at'])
        self.assertEqual(self.executions(job), [])
        self.service.store.pause(False, self.config.owner)
        self.assertEqual(self.service.schedule()['executed'], 1)
        self.sdk("from cron.jobs import pause_job; pause_job(values['id'], reason='owner pause')", id=job['id'])
        current = self.service.schedule()['job']
        self.assertFalse(current['enabled'])
        self.assertEqual(current['paused_reason'], 'owner pause')

    def test_config_disable_reenable_and_native_edits(self):
        job = self.service.schedule()['job']
        edited = self.update(job, schedule='every 5m')
        self.assertEqual(self.service.schedule()['job']['next_run_at'], edited['next_run_at'])
        self.config.data['schedules']['audit_interval_seconds'] = 0
        disabled = self.service.schedule()['job']
        self.assertFalse(disabled['enabled'])
        self.config.data['schedules']['audit_interval_seconds'] = 120
        resumed = self.service.schedule()['job']
        self.assertEqual(resumed['id'], job['id'])
        self.assertTrue(resumed['enabled'])
        self.assertEqual(resumed['schedule']['minutes'], 2)

    def test_isolation_and_competing_adapter_are_rejected(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-should-not-copy', 'GH_TOKEN': 'synthetic-should-not-copy'}):
            job = self.service.schedule()['job']
        self.assertFalse(any(b'synthetic-should-not-copy' in p.read_bytes() for p in self.home.rglob('*') if p.is_file()))
        with (self.home / 'adapter.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(Conflict):
                self.service.schedule()
        self.update(job, deliver='telegram')
        with self.assertRaisesRegex(MikasaError, '不兼容任务'):
            self.service.schedule()
        self.assertEqual(self.service.tasks.list(), [])

    def test_native_script_failure_is_durable_and_reported(self):
        job = self.service.schedule()['job']
        self.due(job)
        root = self.path / 'broken-project'
        scripts = root / 'workers/hermes'
        scripts.mkdir(parents=True)
        for name in ('cron_adapter.py', 'cron_enqueue.py'):
            text = (ROOT / 'workers/hermes' / name).read_text()
            # Keep this synthetic project importable while replacing only its
            # board executable, so the actual native script runner sees failure.
            text = 'import sys\nsys.path.insert(0, ' + repr(str(ROOT)) + ')\n' + text
            (scripts / name).write_text(text)
        (scripts / 'kanban_adapter.py').write_text('raise SystemExit(1)\n')
        broken = Config(root, self.config.data)
        with self.assertRaisesRegex(MikasaError, '原生定时审计失败'):
            Cron(broken, self.service.tasks).tick()
        execution, = self.executions(job)
        self.assertEqual(execution['status'], 'failed')
        self.assertTrue(execution['error'])
        self.assertEqual(self.service.tasks.list(), [])
        self.assertEqual(self.service.schedule()['executed'], 0)

    def test_native_pending_slot_survives_dead_dispatcher(self):
        job = self.service.schedule()['job']
        due = self.due(job)
        # The real SDK process advances the due slot and then exits before
        # dispatch, precisely the native crash-recovery boundary.
        self.sdk("from cron.jobs import get_due_jobs,advance_next_runs; get_due_jobs(); advance_next_runs([values['id']])", id=job['id'])
        self.assertEqual(self.service.schedule()['executed'], 1)
        task, = self.service.tasks.list()
        execution, = self.executions(job)
        self.assertEqual(datetime.fromisoformat(execution['scheduled_instant']), datetime.fromisoformat(due['next_run_at']))
        self.assertIn(execution['scheduled_instant'], task['request_key'])
        self.assertEqual(self.service.schedule()['executed'], 0)
