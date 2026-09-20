import json
import tempfile
import unittest
from pathlib import Path

from mikasa.config import Config
from mikasa.engineering import engineering_profile
from mikasa.errors import Conflict, Forbidden, MikasaError
from mikasa.native import profile_home
from tests.support import ROOT


class EngineeringProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='engineering-unit-')
        self.addCleanup(self.temp.cleanup)
        data = json.loads((ROOT / 'config/examples/mikasa.json').read_text())
        data.update(runtime=self.temp.name, members=['human'])
        self.config = Config(ROOT, data)
        self.task = {'id': 'task-one', 'actor': self.config.owner,
                     'payload': {'repo': 'local/fixture', 'kind': 'plan'}}

    def profile(self, task=None):
        return engineering_profile(self.config, task or self.task, [{'name': 'mikasa-persona'}], {'backend': 'docker'})

    def test_tasks_bind_one_native_memory_directory_without_touching_chat_config(self):
        account = profile_home(self.config, self.config.owner)
        (account / 'memories').mkdir(parents=True)
        (account / 'memories/MEMORY.md').write_text('confirmed convention')
        (account / 'config.yaml').write_text('existing native preferences')
        (account / 'state.db').write_bytes(b'chat history')
        with self.profile() as home:
            self.assertEqual((home / 'memories/MEMORY.md').read_text(), 'confirmed convention')
            (home / 'memories/USER.md').write_text('shared account fact')
            (home / 'state.db').write_bytes(b'task history')
        with self.profile({**self.task, 'id': 'task-two'}) as other:
            self.assertEqual((other / 'memories/USER.md').read_text(), 'shared account fact')
            self.assertFalse((other / 'state.db').exists())
        self.assertEqual((account / 'config.yaml').read_text(), 'existing native preferences')
        self.assertEqual((account / 'state.db').read_bytes(), b'chat history')

    def test_member_task_never_inherits_owner_memory(self):
        with self.profile() as owner:
            (owner / 'memories/MEMORY.md').write_text('owner private preference')
        member = {**self.task, 'id': 'member-task', 'actor': 'human'}
        with self.profile(member) as home:
            self.assertFalse((home / 'memories/MEMORY.md').exists())
            self.assertEqual((home / 'memories').resolve(), profile_home(self.config, 'human') / 'memories')
        with self.assertRaises(Forbidden), self.profile({**member, 'actor': 'unknown'}):
            pass

    def test_legacy_task_memory_and_sessions_are_retained_without_account_merge(self):
        home = self.config.runtime / 'engineering' / self.task['id']
        (home / 'memories').mkdir(parents=True)
        (home / 'memories/MEMORY.md').write_text('old repository-specific notes')
        (home / 'state.db').write_bytes(b'legacy native sessions')
        for _ in range(2):
            with self.profile() as prepared:
                self.assertEqual(prepared, home)
                self.assertEqual((home / 'memories.legacy/MEMORY.md').read_text(), 'old repository-specific notes')
                self.assertFalse((home / 'memories/MEMORY.md').exists())
                self.assertEqual((home / 'state.db').read_bytes(), b'legacy native sessions')

    def test_account_and_repo_binding_cannot_change_on_retry(self):
        with self.profile():
            pass
        for changed in ({**self.task, 'actor': 'human'},
                        {**self.task, 'payload': {'repo': 'another/repo'}}):
            with self.assertRaisesRegex(MikasaError, '绑定不匹配'), self.profile(changed):
                pass

    def test_concurrent_task_refused_and_lock_released_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'worker failure'):
            with self.profile():
                with self.assertRaises(Conflict), self.profile():
                    pass
                raise RuntimeError('worker failure')
        with self.profile():
            pass

    def test_unexpected_memory_link_is_not_replaced(self):
        home = self.config.runtime / 'engineering' / self.task['id']
        home.mkdir(parents=True)
        destination = Path(self.temp.name) / 'other-account'
        destination.mkdir()
        (home / 'memories').symlink_to(destination)
        with self.assertRaisesRegex(MikasaError, '其他账号'), self.profile():
            pass
        self.assertEqual((home / 'memories').resolve(), destination.resolve())

    def test_archive_conflict_preserves_all_original_data(self):
        home = self.config.runtime / 'engineering' / self.task['id']
        for directory in ('memories', 'memories.legacy'):
            (home / directory).mkdir(parents=True)
            (home / directory / 'MEMORY.md').write_text(directory)
        with self.assertRaisesRegex(MikasaError, '归档冲突'), self.profile():
            pass
        for directory in ('memories', 'memories.legacy'):
            self.assertEqual((home / directory / 'MEMORY.md').read_text(), directory)

    def test_task_path_cannot_escape_runtime(self):
        with self.assertRaisesRegex(MikasaError, '任务 ID'), self.profile({**self.task, 'id': '../escape'}):
            pass

    def test_workspace_link_and_dangling_env_rejected_before_binding(self):
        home = self.config.runtime / 'engineering' / self.task['id']
        home.mkdir(parents=True)
        for name in ('workspace', '.env'):
            with self.subTest(name=name):
                link = home / name
                link.symlink_to(self.config.runtime / 'absent')
                with self.assertRaises(MikasaError), self.profile():
                    pass
                self.assertFalse((home / 'binding.json').exists())
                link.unlink()

    def test_account_created_by_engineering_is_private(self):
        with self.profile():
            account = profile_home(self.config, self.config.owner)
            self.assertEqual(account.stat().st_mode & 0o777, 0o700)
            self.assertEqual((account / 'memories').stat().st_mode & 0o777, 0o700)
