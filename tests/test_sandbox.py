import json
import os
from unittest.mock import patch

from mikasa.errors import MikasaError
from mikasa.native_tools import NativeToolSession
from mikasa.process import git
from mikasa.sandbox import Snapshot
from mikasa.workspace import Workspace
from tests.support import BaseTest


class NativeSandboxTests(BaseTest):
    def workspace(self):
        return Workspace(self.config, self.submit(), 'native').prepare()

    def commit(self, w):
        git(['add', '.'], w.path)
        w.head = w.commit()

    def test_export_pins_review_head_excludes_secrets_links_and_agent_config(self):
        w = self.workspace()
        (w.path / 'app.py').write_text('VALUE = 3\n')
        (w.path / '.hermes').mkdir()
        (w.path / '.hermes/config.yaml').write_text('untrusted')
        (w.path / 'auth.json').write_text('fixture secret')
        (w.path / 'link').symlink_to('app.py')
        self.commit(w)
        git(['checkout', w.base], w.path)
        with Snapshot(w, 'review') as snapshot:
            self.assertEqual((snapshot.path / 'app.py').read_text(), 'VALUE = 3\n')
            self.assertFalse((snapshot.path / '.git').exists())
            self.assertEqual(set(snapshot.omitted), {'.hermes/config.yaml', 'auth.json', 'link'})
            self.assertTrue(snapshot.terminal_config()['docker_volumes'][0].endswith(':ro'))
            (snapshot.path / 'app.py').write_text('changed')
            with self.assertRaisesRegex(MikasaError, '只读'):
                snapshot.apply()

    def test_staged_repair_snapshot_and_exact_delta_import(self):
        w = self.workspace()
        w.apply([{'path': 'app.py', 'content': 'VALUE = 2\n'}])
        with Snapshot(w, 'implement') as snapshot:
            self.assertEqual((snapshot.path / 'app.py').read_text(), 'VALUE = 2\n')
            (snapshot.path / 'app.py').write_text('VALUE = 4\n')
            (snapshot.path / 'new.txt').write_bytes(b'hello\n')
            snapshot.apply()
            self.assertEqual((w.path / 'new.txt').read_bytes(), b'hello\n')
            self.assertEqual(snapshot.apply(), [])
            (snapshot.path / 'new.txt').unlink()
            snapshot.apply()
            self.assertFalse((w.path / 'new.txt').exists())

    def test_invalid_delta_never_applies_earlier_valid_file(self):
        w = self.workspace()
        with Snapshot(w, 'implement') as snapshot:
            (snapshot.path / 'app.py').write_text('VALUE = 2\n')
            (snapshot.path / 'identity.md').write_text('replace owner')
            with self.assertRaises(MikasaError):
                snapshot.apply()
            self.assertEqual((w.path / 'app.py').read_text(), 'VALUE = 1\n')
            self.assertFalse(git(['diff', '--cached', '--stat'], w.path))

    def test_special_files_permissions_and_hardlinks_fail_closed(self):
        w = self.workspace()
        for fixture in ('symlink', 'fifo', 'hardlink', 'mode', 'binary'):
            with Snapshot(w, 'implement') as snapshot:
                target = snapshot.path / 'bad'
                if fixture == 'symlink':
                    target.symlink_to('/etc/passwd')
                elif fixture == 'fifo':
                    os.mkfifo(target)
                elif fixture == 'hardlink':
                    os.link(snapshot.path / 'app.py', target)
                elif fixture == 'mode':
                    (snapshot.path / 'app.py').chmod(0o777)
                else:
                    target.write_bytes(b'\0bad')
                with self.assertRaises(MikasaError, msg=fixture):
                    snapshot.apply()

    def test_native_review_evidence_requires_every_exact_line(self):
        w = self.workspace()
        (w.path / 'long.txt').write_text('first\nsecond\nthird\n')
        self.commit(w)
        with Snapshot(w, 'review') as snapshot:
            event = snapshot.observe_read('/workspace/long.txt', {'content': '3|third', 'total_lines': 3})
            self.assertFalse(event['complete'])
            self.assertFalse(snapshot.observe_read('long.txt', {'content': '1|forged\n2|second'})['complete'])
            self.assertFalse(snapshot.observe_read('long.txt', {'error': 'blocked'}))
            event = snapshot.observe_read('long.txt', json.dumps({'content': '1|first'}))
            self.assertTrue(event['complete'])
            self.assertEqual(event['revision'], w.head)
            self.assertEqual(len(event['sha256']), 64)
            self.assertEqual(snapshot.observe_read('../long.txt', {'content': '1|first'}), {})

    def test_excluded_binary_cannot_be_overwritten_through_snapshot(self):
        w = self.workspace()
        (w.path / 'binary.dat').write_bytes(b'\0binary')
        self.commit(w)
        with Snapshot(w, 'implement') as snapshot:
            self.assertIn('binary.dat', snapshot.omitted)
            (snapshot.path / 'binary.dat').write_text('replacement')
            with self.assertRaisesRegex(MikasaError, '未导出'):
                snapshot.apply()
        self.assertEqual((w.path / 'binary.dat').read_bytes(), b'\0binary')

    def test_failed_container_removal_retains_snapshot(self):
        w = self.workspace()
        session = NativeToolSession(w, 'implement', lambda: False)
        session.__enter__()
        try:
            with patch.object(session, 'containers', return_value=['own-id']), patch.object(session, 'docker', side_effect=MikasaError('unavailable')):
                with self.assertRaises(MikasaError):
                    session.__exit__()
            self.assertTrue(session.snapshot.path.exists())
        finally:
            session.snapshot.__exit__()

    def test_checkpoint_progress_failure_precedes_host_import(self):
        w = self.workspace()
        def fail(_):
            raise MikasaError('event store unavailable')
        with patch.object(NativeToolSession, 'docker', return_value=''):
            with NativeToolSession(w, 'implement', lambda: False, progress=fail) as session:
                (session.snapshot.path / 'app.py').write_text('VALUE = 2\n')
                self.assertIn('error', session.call('mikasa_run_checks', {}))
                self.assertTrue(session.fatal)
                self.assertEqual((w.path / 'app.py').read_text(), 'VALUE = 1\n')

    def test_native_session_only_exposes_business_check_tool(self):
        w = self.workspace()
        with patch.object(NativeToolSession, 'docker', return_value=''):
            with NativeToolSession(w, 'implement', lambda: False) as session:
                self.assertEqual([s['name'] for s in session.schemas], ['mikasa_run_checks'])
                self.assertIn('error', session.call('mikasa_apply_changes', {'changes': []}))
                (session.snapshot.path / 'app.py').write_text('VALUE = 2\n')
                self.assertTrue(session.call('mikasa_run_checks', {})['passed'])
                session.finish()
                self.assertTrue(session.applied)
            with NativeToolSession(w, 'review', lambda: False) as session:
                self.assertNotIn('write_file', session.native_grants)
                self.assertIn('error', session.call('mikasa_run_checks', {}))

    def test_checkpoint_freezes_and_cleanup_removes_only_owned_containers(self):
        w = self.workspace()
        calls = []
        def docker(args):
            calls.append(args)
            return 'own-id\n' if args[0] == 'ps' else ''
        with patch.object(NativeToolSession, 'docker', side_effect=docker):
            with NativeToolSession(w, 'implement', lambda: False) as session:
                session.call('mikasa_run_checks', {})
                session_id = session.native_id
        self.assertIn(['pause', 'own-id'], calls)
        self.assertIn(['unpause', 'own-id'], calls)
        self.assertIn(['rm', '-f', 'own-id'], calls)
        self.assertTrue(all(c[-1] == 'label=hermes-task-id=' + session_id for c in calls if c[0] == 'ps'))
