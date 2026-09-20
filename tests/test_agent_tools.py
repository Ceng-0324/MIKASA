import json
import sys

from mikasa.agent_tools import ToolSession
from mikasa.errors import MikasaError
from mikasa.process import git
from mikasa.workspace import Workspace
from tests.support import BaseTest, REPO


class AgentToolTests(BaseTest):
    def workspace(self, kind="implement"):
        task = self.submit(kind)
        return Workspace(self.config, task, "tools").prepare()

    def test_real_process_channel_repairs_and_host_validates(self):
        script = self.path / "worker.py"
        script.write_text('''import json, os, socket, sys
request = json.load(sys.stdin)
s = socket.socket(fileno=int(os.environ['MIKASA_TOOL_FD'])).makefile('rwb')
def call(name, args):
    s.write(json.dumps({'name': name, 'arguments': args}).encode()+b'\\n'); s.flush()
    return json.loads(s.readline())
assert 'app.py' in call('mikasa_list_files', {})['files']
assert call('mikasa_search', {'query': 'VALUE'})['matches']
assert 'VALUE = 1' in call('mikasa_read_file', {'path': 'app.py'})['content']
assert not call('mikasa_run_checks', {})['passed']
assert call('mikasa_apply_changes', {'changes': [{'path':'app.py','content':'VALUE = 2\\n'}]})['applied']
assert call('mikasa_run_checks', {})['passed']
print(json.dumps({'version':1,'runtime':{'backend':'fixture', 'tool_events':['forged']},'result':{'summary':'fixed','changes':[]}}))
''')
        self.config.data["worker"]["command"] = [sys.executable, str(script)]
        self.submit()
        finished = self.service.run_once()
        self.assertEqual(finished["state"], "awaiting_review", finished.get("error"))
        result = finished["result"]
        events = result["execution"]["tool_events"]
        self.assertEqual(len(events), 6)
        self.assertNotEqual(events[3]["checks"][0]["code"], 0)
        self.assertEqual(events[-1]["checks"][0]["code"], 0)
        self.assertEqual(result["checks"][0]["code"], 0)
        self.assertNotEqual(result["head"], result["base"])

    def test_readonly_pinned_head_and_access_boundaries(self):
        w = self.workspace("plan")
        (w.path / 'app.py').write_text('VALUE = 3\n')
        git(['add', '.'], w.path)
        w.head = w.commit()
        git(['checkout', w.base], w.path)
        session = ToolSession(w, 'review', lambda: False)
        self.assertIn('VALUE = 3', session.call('mikasa_read_file', {'path': 'app.py'})['content'])
        for name, args in [('mikasa_apply_changes', {'changes': []}), ('mikasa_run_checks', {}),
                           ('mikasa_read_file', {'path': '../auth.json'}), ('mikasa_read_file', {'path': '.git/config'})]:
            self.assertIn('error', session.call(name, args))

    def test_secrets_symlinks_rules_and_commands_denied(self):
        w = self.workspace()
        (w.path / 'auth.json').write_text('SECRET')
        (w.path / 'link').symlink_to(w.path / 'app.py')
        git(['add', '.'], w.path)
        session = ToolSession(w, 'implement', lambda: False)
        self.assertNotIn('auth.json', session.call('mikasa_list_files', {})['files'])
        for path in ['auth.json', 'link', '../escape', 'AGENTS.md', '.github/workflows/ci.yml']:
            self.assertIn('error', session.call('mikasa_apply_changes', {'changes': [{'path': path, 'content': 'bad'}]}))
        self.assertIn('error', session.call('mikasa_read_file', {'path': 'link'}))
        self.assertIn('error', session.call('mikasa_run_checks', {'command': ['echo', 'bad']}))

    def test_check_corruption_is_fatal_even_if_agent_ignores_error(self):
        w = self.workspace()
        session = ToolSession(w, 'implement', lambda: False)
        session.call('mikasa_apply_changes', {'changes': [{'path': 'app.py', 'content': 'VALUE = 2\n'}]})
        w.spec['checks'] = [[sys.executable, '-c', "from pathlib import Path; Path('app.py').write_text('VALUE = 4')"]]
        self.assertIn('error', session.call('mikasa_run_checks', {}))
        self.assertIsNotNone(session.fatal)
        self.assertIn('error', session.call('mikasa_apply_changes', {'changes': [{'path': 'app.py', 'content': 'VALUE = 2\n'}]}))

    def test_shutdown_cancels_check_and_joins_thread(self):
        import time
        w = self.workspace()
        w.spec['checks'] = [[sys.executable, '-c', 'import time; time.sleep(30)']]
        start = time.monotonic()
        with ToolSession(w, 'implement', lambda: False) as session:
            session.child.sendall(b'{"name":"mikasa_run_checks","arguments":{}}\n')
            time.sleep(0.3)
        self.assertLess(time.monotonic() - start, 3)
        self.assertFalse(session.thread.is_alive())

    def test_empty_changes_cannot_fake_tool_work(self):
        from mikasa.worker import Worker
        w = self.workspace()
        self.config.data['worker']['command'] = [sys.executable, '-c', "print('{\"version\":1,\"runtime\":{},\"result\":{\"summary\":\"fake\",\"changes\":[]}}')"]
        with self.assertRaisesRegex(MikasaError, '空 changes'):
            Worker(self.config).execute(w.task, {}, lambda: False, workspace=w)

    def test_host_read_evidence_resolves_omitted_review_file(self):
        base = git(['rev-parse', 'HEAD'], self.repo)
        (self.repo / 'app.py').write_text('VALUE = 2\n')
        git(['add', '.'], self.repo)
        git(['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'human change'], self.repo)
        head = git(['rev-parse', 'HEAD'], self.repo)
        git(['update-ref', 'refs/pull/1/head', head], self.repo)
        git(['update-ref', 'refs/heads/main', base], self.repo)
        self.github.current['base']['sha'] = base
        self.github.current['head']['sha'] = head
        self.service.store.provenance(REPO, 1, head, 'human', self.config.owner)
        script = self.path / 'reviewer.py'
        script.write_text('''import json, os, socket, sys
request = json.load(sys.stdin)
s = socket.socket(fileno=int(os.environ['MIKASA_TOOL_FD'])).makefile('rwb')
s.write(b'{"name":"mikasa_read_file","arguments":{"path":"app.py"}}\\n'); s.flush()
response = json.loads(s.readline())
assert 'VALUE = 2' in response['content']
print(json.dumps({'version':1,'runtime':{'backend':'fixture'},'result':{'summary':'ok','verdict':'APPROVED','basis':['VALUE equals 2'],'findings':[],'limitations':[]}}))
''')
        self.config.data['worker']['command'] = [sys.executable, str(script)]
        self.config.data['worker']['max_context_bytes'] = 1
        self.submit('review', pr=1)
        result = self.service.run_once()
        self.assertEqual(result['state'], 'done', result.get('error'))
        self.assertEqual(result['result']['verdict'], 'APPROVED')
        event = result['result']['execution']['tool_events'][0]
        self.assertEqual(event['revision'], head)
        self.assertEqual(len(event['sha256']), 64)

    def test_tool_budget_and_search_limit_are_explicit(self):
        w = self.workspace()
        (w.path / 'app.py').write_text('VALUE = 1\n' * 120)
        session = ToolSession(w, 'implement', lambda: False)
        result = session.call('mikasa_search', {'query': 'VALUE'})
        self.assertEqual(len(result['matches']), 100)
        self.assertTrue(result['truncated'])
        self.assertIn('error', session.call('mikasa_search', {'query': ''}))
        session.events = [{}] * 64
        self.assertIn('error', session.call('mikasa_apply_changes', {'changes': [{'path': 'new.py', 'content': 'bad'}]}))
        self.assertFalse((w.path / 'new.py').exists())

    def test_pinned_read_preserves_whitespace_and_digest(self):
        import hashlib
        w = self.workspace('plan')
        content = '\n    indented\n\n'
        (w.path / ' leading.txt').write_text(content)
        git(['add', '.'], w.path)
        w.head = w.commit()
        session = ToolSession(w, 'plan', lambda: False)
        self.assertIn(' leading.txt', session.call('mikasa_list_files', {})['files'])
        self.assertEqual(session.call('mikasa_read_file', {'path': ' leading.txt'})['content'], content)
        self.assertEqual(session.events[-1]['sha256'], hashlib.sha256(content.encode()).hexdigest())

    def test_file_paths_cannot_expand_git_pathspec(self):
        w = self.workspace()
        (w.path / 'auth.json').write_text('private fixture')
        session = ToolSession(w, 'implement', lambda: False)
        self.assertTrue(session.call('mikasa_apply_changes', {'changes': [{'path': '*', 'content': 'literal filename\n'}]})['applied'])
        staged = git(['diff', '--cached', '--name-only'], w.path)
        self.assertEqual(staged, '*')
