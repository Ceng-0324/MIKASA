import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('vm_manage', Path(__file__).resolve().parents[1] / 'deploy/vm/manage.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


class VMOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def release(self, revision, text='identity'):
        root = self.root / revision
        root.mkdir()
        (root / 'identity.md').write_text(text)
        (root / 'release.json').write_text(json.dumps({'revision': revision, 'files': {
            'identity.md': hashlib.sha256(text.encode()).hexdigest()}}))
        return root

    def test_manifest_rejects_corruption_extra_files_and_unsafe_revision(self):
        root = self.release('a' * 40)
        vm.validate_release(root)
        (root / 'identity.md').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, '校验失败'):
            vm.validate_release(root)
        (root / 'identity.md').write_text('identity')
        (root / 'injected.py').write_text('unexpected')
        with self.assertRaisesRegex(RuntimeError, '未登记'):
            vm.validate_release(root)
        (root / 'release.json').write_text(json.dumps({'revision': '../outside', 'files': {}}))
        with self.assertRaisesRegex(RuntimeError, '非法'):
            vm.validate_release(root)

    def test_in_place_legacy_directory_is_valid_rollback_target(self):
        legacy = self.root / 'legacy-1727000000'
        legacy.mkdir()
        (legacy / 'runtime-state.db').write_text('kept')
        self.assertEqual(vm.validate_release(legacy)['revision'], legacy.name)

    def test_release_parent_is_explicitly_traversable_under_private_umask(self):
        releases = self.root / 'releases'
        with patch.object(vm, 'RELEASES', releases):
            old_umask = __import__('os').umask(0o077)
            try:
                releases.mkdir(mode=0o755, exist_ok=True)
                releases.chmod(0o755)
            finally:
                __import__('os').umask(old_umask)
        self.assertEqual(releases.stat().st_mode & 0o777, 0o755)

    def test_release_tree_permissions_allow_service_user_to_import(self):
        root = self.root / 'release'
        package = root / 'mikasa'
        package.mkdir(parents=True, mode=0o700)
        (package / '__main__.py').write_text('')
        root.chmod(0o700)
        vm.normalize_release_permissions(root)
        self.assertEqual(root.stat().st_mode & 0o777, 0o755)
        self.assertEqual(package.stat().st_mode & 0o777, 0o755)
        self.assertEqual((package / '__main__.py').stat().st_mode & 0o777, 0o644)

    def test_tar_rejects_traversal_links_and_duplicates(self):
        for name, kind in [('../outside', 'file'), ('/absolute', 'file'), ('link', 'link'), ('same', 'duplicate')]:
            archive = self.root / 'bad.tar'
            with tarfile.open(archive, 'w') as target:
                item = tarfile.TarInfo(name)
                if kind == 'link':
                    item.type, item.linkname = tarfile.SYMTYPE, '/etc'
                target.addfile(item)
                if kind == 'duplicate':
                    target.addfile(item)
            with self.assertRaises(RuntimeError):
                vm.unpack(archive, self.root / 'extracted')
        self.assertFalse((self.root / 'outside').exists())

    def test_failed_new_release_rolls_back_without_restoring_data(self):
        old = self.release('a' * 40)
        new = self.release('b' * 40)
        app = self.root / 'current'
        app.symlink_to(old)
        with patch.object(vm, 'APP', app), patch.object(vm, 'BACKUP_ENV', self.root), \
                patch.object(vm, 'stopped', contextlib.nullcontext), patch.object(vm, 'snapshot', return_value='snapshot'), \
                patch.object(vm, 'wait_healthy', side_effect=[RuntimeError('unhealthy'), None]), \
                patch.object(vm, 'skill_roots', return_value={'profile': ['old-skills']}) as roots, \
                patch.object(vm, 'run') as run, \
                patch.object(vm.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(RuntimeError, '回切旧代码'):
                vm.switch(new)
        self.assertEqual(app.resolve(), old)
        roots.assert_called_with({'profile': ['old-skills']})
        self.assertEqual([c.args[:2] for c in run.call_args_list],
            [('systemctl', 'stop'), ('systemctl', 'reset-failed'), ('systemctl', 'start')])

    def test_backup_failure_does_not_switch_release(self):
        old = self.release('a' * 40)
        new = self.release('b' * 40)
        app = self.root / 'current'
        app.symlink_to(old)
        with patch.object(vm, 'APP', app), patch.object(vm, 'stopped', contextlib.nullcontext), \
                patch.object(vm, 'snapshot', side_effect=RuntimeError('disk full')), \
                patch.object(vm.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(RuntimeError, 'disk full'):
                vm.switch(new)
        self.assertEqual(app.resolve(), old)

    def test_maintenance_always_restarts_and_refuses_busy_work(self):
        with patch.object(vm, 'STATE', self.root), patch.object(vm, 'run') as run, \
                patch.object(vm, 'drained', return_value=contextlib.nullcontext()), \
                patch.object(vm, 'live_state', return_value=[{'active_agents': 0}]), \
                patch.object(vm.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(RuntimeError, 'backup failed'):
                with vm.stopped():
                    raise RuntimeError('backup failed')
            self.assertEqual([c.args[:2] for c in run.call_args_list],
                [('systemctl', 'stop'), ('systemctl', 'reset-failed'), ('systemctl', 'start')])
            run.reset_mock()
            with patch.object(vm, 'live_state', return_value=[{'active_agents': 1}]):
                with self.assertRaisesRegex(RuntimeError, '任务'):
                    with vm.stopped():
                        self.fail('must not stop active work')
            run.assert_not_called()

    def test_independent_engineering_lock_prevents_snapshot_and_restarts(self):
        import fcntl
        with (self.root / 'maintenance.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            with patch.object(vm, 'STATE', self.root), patch.object(vm, 'run') as run, \
                    patch.object(vm, 'drained', return_value=contextlib.nullcontext()), \
                    patch.object(vm, 'live_state', return_value=[{'active_agents': 0}]), \
                    patch.object(vm.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaises(BlockingIOError):
                    with vm.stopped():
                        self.fail('engineering is running')
                self.assertEqual(run.call_args.args, ('systemctl', 'start', vm.SERVICE))

    def test_native_drain_waits_for_ack_and_cancels_on_timeout(self):
        home = self.root / 'profile'
        home.mkdir()
        states = [{'_home': str(home), 'gateway_state': 'running', 'active_agents': 0}]
        marker = home / '.drain_request.json'
        def mark(*args, **kwargs):
            marker.write_text('{}')
        with patch.object(vm, 'run', side_effect=mark), patch.object(vm.time, 'sleep'), \
                patch.object(vm.time, 'monotonic', side_effect=[0, 0, 31]), \
                patch.object(vm, 'live_state', return_value=states):
            with self.assertRaisesRegex(RuntimeError, '排空未完成'):
                with vm.drained(states):
                    self.fail('must not stop without native acknowledgement')
        self.assertFalse(marker.exists())
        states[0]['gateway_state'] = 'draining'
        with patch.object(vm, 'run', side_effect=mark), patch.object(vm, 'live_state', return_value=states):
            with vm.drained(states):
                self.assertTrue(marker.exists())
        self.assertFalse(marker.exists())

    def test_other_maintainers_drain_marker_is_preserved(self):
        marker = self.root / '.drain_request.json'
        marker.write_text('another maintainer')
        with self.assertRaisesRegex(RuntimeError, '已有原生维护请求'):
            with vm.drained([{'_home': str(self.root)}]):
                self.fail('must not overwrite another maintainer')
        self.assertEqual(marker.read_text(), 'another maintainer')
