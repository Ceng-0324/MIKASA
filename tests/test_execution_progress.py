import json
import sys
import threading
import time

from mikasa.errors import Conflict
from mikasa.kanban import Kanban
from tests.support import BaseTest


class ExecutionProgressTests(BaseTest):
    def install_worker(self, tail):
        script = self.path / 'progress_worker.py'
        script.write_text('''import json, os, socket, sys, time
request = json.load(sys.stdin)
s = socket.socket(fileno=int(os.environ['MIKASA_TOOL_FD'])).makefile('rwb')
def call(name, args):
    s.write(json.dumps({'name':name,'arguments':args}).encode()+b'\\n'); s.flush()
    return json.loads(s.readline())
call('mikasa_read_file', {'path':'app.py'})
''' + tail)
        self.config.data['worker']['command'] = [sys.executable, str(script)]

    def test_progress_is_queryable_before_worker_returns_and_survives_failure(self):
        self.install_worker("time.sleep(1); print('private-model-diagnostic', file=sys.stderr); sys.exit(1)\n")
        task = self.submit()
        thread = threading.Thread(target=self.service.run_once)
        thread.start()
        self.addCleanup(lambda: thread.join(10))
        deadline = time.monotonic() + 10
        observed = None
        while time.monotonic() < deadline:
            events = self.service.tasks.events(task['id'])
            if any(e['kind'] == 'execution' and e['data'].get('phase') == 'tool' and e['data']['status'] == 'completed' for e in events):
                observed = self.service.tasks.get(task['id'])['state']
                break
            time.sleep(.02)
        self.assertEqual(observed, 'running')
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.service.tasks.get(task['id'])['state'], 'failed')
        events = Kanban(self.config).events(task['id'])
        data = [e['data'] for e in events if e['kind'] == 'execution']
        self.assertEqual(data[-1]['phase'], 'worker')
        self.assertEqual(data[-1]['status'], 'failed')
        self.assertNotIn('private-model-diagnostic', json.dumps(events))
        self.assertNotIn('VALUE = 1', json.dumps(events))
        self.assertTrue(any(e.get('complete') for e in data))

    def test_timeout_preserves_tool_evidence(self):
        self.install_worker('time.sleep(30)\n')
        self.config.data['worker']['timeout'] = 2
        task = self.submit()
        result = self.service.run_once()
        self.assertEqual(result['state'], 'failed')
        self.assertIn('超时', result['error'])
        events = self.service.tasks.events(task['id'])
        self.assertTrue(any(e['data'].get('tool') == 'mikasa_read_file' and e['data'].get('ok') for e in events))

    def test_stale_runner_cannot_append_after_cancel_or_retry(self):
        task = self.submit()
        _, old_token = self.service.tasks.claim(self.config.bot)
        self.service.tasks.record_execution(task['id'], old_token, {'phase':'worker','status':'started'})
        self.service.action(task['id'], 'cancel', self.config.owner)
        with self.assertRaises(Conflict):
            self.service.tasks.record_execution(task['id'], old_token, {'phase':'tool'})
        self.service.action(task['id'], 'retry', self.config.owner)
        _, new_token = self.service.tasks.claim(self.config.bot)
        with self.assertRaises(Conflict):
            self.service.tasks.record_execution(task['id'], old_token, {'phase':'tool'})
        self.service.tasks.record_execution(task['id'], new_token, {'phase':'worker','status':'started'})
        self.assertEqual(len([e for e in self.service.tasks.events(task['id']) if e['kind']=='execution']), 2)

    def test_recovery_retains_last_observed_phase(self):
        task = self.submit()
        _, token = self.service.tasks.claim(self.config.bot)
        self.service.tasks.record_execution(task['id'], token, {'phase':'tool','status':'started','tool':'mikasa_run_checks'})
        self.service.tasks.recover('runtime')
        events = self.service.tasks.events(task['id'])
        self.assertEqual([e for e in events if e['kind'] == 'execution'][-1]['data']['status'], 'started')
        self.assertEqual(events[-1]['kind'], 'interrupted')
        self.assertEqual(self.service.tasks.get(task['id'])['state'], 'failed')

    def test_success_records_validation_commit_and_unforgeable_tool_events(self):
        self.install_worker('''call('mikasa_apply_changes', {'changes':[{'path':'app.py','content':'VALUE = 2\\n'}]})
print(json.dumps({'version':1,'runtime':{'backend':'fixture','tool_events':['fake']},'result':{'summary':'done','changes':[]}}))
''')
        task = self.submit()
        result = self.service.run_once()
        self.assertEqual(result['state'], 'awaiting_review', result.get('error'))
        events = self.service.tasks.events(task['id'])
        data = [e['data'] for e in events if e['kind']=='execution']
        self.assertEqual(data[-1]['phase'], 'commit')
        self.assertEqual(data[-1]['head'], result['result']['head'])
        self.assertTrue(any(e.get('checks') == [{'code':0,'index':0}] for e in data))
        calls = [e for e in data if e['phase']=='tool']
        self.assertEqual(len(calls),4)
        self.assertEqual(len({e['invocation'] for e in calls}),1)
        self.assertNotIn('fake', json.dumps(events))

    def test_progress_write_failure_prevents_mutation(self):
        from mikasa.agent_tools import ToolSession
        from mikasa.workspace import Workspace
        w = Workspace(self.config, self.submit(), 'progress').prepare()
        def failed(data):
            raise Conflict('lost lease')
        session = ToolSession(w, 'implement', lambda: False, progress=failed)
        with self.assertRaises(Conflict):
            session.call('mikasa_apply_changes', {'changes':[{'path':'app.py','content':'VALUE = 2\n'}]})
        self.assertEqual((w.path / 'app.py').read_text(), 'VALUE = 1\n')

    def test_cancel_stops_live_worker_without_late_progress(self):
        self.install_worker('time.sleep(30)\n')
        task = self.submit()
        thread = threading.Thread(target=self.service.run_once)
        thread.start()
        self.addCleanup(lambda: thread.join(10))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            events = self.service.tasks.events(task['id'])
            if any(e['data'].get('tool') == 'mikasa_read_file' and e['data'].get('ok') for e in events):
                break
            time.sleep(.02)
        else:
            self.fail('worker did not emit progress')
        self.service.action(task['id'], 'cancel', self.config.owner)
        count = len(self.service.tasks.events(task['id']))
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.service.tasks.get(task['id'])['state'], 'cancelled')
        self.assertEqual(len(self.service.tasks.events(task['id'])), count)
