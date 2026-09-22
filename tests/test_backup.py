import fcntl
import json
import socket
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from mikasa.backup import backup_state, restore_state
from mikasa.errors import Conflict, MikasaError
from mikasa.maintenance import runtime_lock
from mikasa.native import NativeGateway
from mikasa.process import git
from tests.support import BaseTest


class BackupTests(BaseTest):
    def test_chat_workspace_sources_survive_without_native_control_socket(self):
        home = self.config.runtime / 'native/account'
        workspace = home / 'workspace'
        workspace.mkdir(parents=True)
        sources = {'cache/source.py': b'CACHE_IMPLEMENTATION = True\n',
                   'logs/example.log': b'project fixture\n',
                   'fixture.db': b'non-SQLite application fixture',
                   'gateway.sock': b'project source, not a runtime socket',
                   'config.yaml': b'api_key: example-value\n'}
        for name, content in sources.items():
            path = workspace / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
        # macOS temp roots can exceed the UDS path limit; move a closed endpoint.
        with tempfile.TemporaryDirectory(dir='/tmp', prefix='mkuds-') as short:
            endpoint = Path(short) / 'gateway.sock'
            with socket.socket(socket.AF_UNIX) as control:
                control.bind(str(endpoint))
            endpoint.rename(home / 'gateway.sock')
        (home / 'gateway.sock.path').write_text('/tmp/obsolete-native-endpoint')
        backup = self.snapshot()
        restored = self.path / 'chat-restored'
        restore_state(self.config, backup, restored)
        for root in (backup, restored):
            copied = root / 'native/account'
            self.assertFalse((copied / 'gateway.sock').exists())
            self.assertFalse((copied / 'gateway.sock.path').exists())
            for name, content in sources.items():
                self.assertEqual((copied / 'workspace' / name).read_bytes(), content)
        self.assertTrue((home / 'gateway.sock').is_socket())

    def test_native_engineering_state_and_v2_archive_restore(self):
        runtime = self.config.runtime
        account = runtime / 'native/account/memories'
        account.mkdir(parents=True)
        (account / 'MEMORY.md').write_text('shared convention')
        home = runtime / 'engineer/account'
        home.mkdir(parents=True)
        (home / 'memories').symlink_to(account)
        board = home / 'kanban'
        board.mkdir()
        workspace = home / 'workspace'
        workspace.mkdir()
        with sqlite3.connect(board / 'kanban.db') as db:
            db.execute('CREATE TABLE tasks(id TEXT, workspace_path TEXT)')
            db.execute('INSERT INTO tasks VALUES(?,?)', ('native', str(workspace)))
        with sqlite3.connect(home / 'state.db') as db:
            db.execute('CREATE TABLE sessions(id TEXT, cwd TEXT, git_repo_root TEXT)')
            db.execute('INSERT INTO sessions VALUES(?,?,?)', ('session', str(workspace), str(workspace)))
        backup = self.snapshot()
        restored = self.path / 'native-restored'
        restore_state(self.config, backup, restored)
        self.assertEqual((restored / 'engineer/account/memories').resolve(), restored / 'native/account/memories')
        with sqlite3.connect(restored / 'engineer/account/state.db') as db:
            self.assertEqual(db.execute('SELECT cwd FROM sessions').fetchone()[0], str(restored / 'engineer/account/workspace'))
        with sqlite3.connect(restored / 'engineer/account/kanban/kanban.db') as db:
            self.assertEqual(db.execute('SELECT workspace_path FROM tasks').fetchone()[0], str(restored / 'engineer/account/workspace'))
        legacy = runtime / 'kanban'
        legacy.mkdir()
        with sqlite3.connect(legacy / 'kanban.db') as db:
            db.execute('CREATE TABLE tasks(id TEXT, workspace_path TEXT, result TEXT)')
        old_backup = self.path / 'v2-backup'
        backup_state(self.config, old_backup)
        marker = old_backup / 'manifest.json'
        manifest = json.loads(marker.read_text())
        manifest['version'] = 2
        marker.write_text(json.dumps(manifest))
        restore_state(self.config, old_backup, self.path / 'v2-restored')
        self.assertTrue((self.path / 'v2-restored/kanban/kanban.db').is_file())

    def snapshot(self):
        target = self.path / 'backup'
        backup_state(self.config, target)
        return target

    def test_round_trip_includes_wal_memory_cron_git_and_relocated_workspaces(self):
        task = {'id': 'legacy-task'}
        workspace = self.config.runtime / 'engineer/account/workspace'
        workspace.parent.mkdir(parents=True)
        git(['clone', str(self.repo), str(workspace)], self.repo)
        result = {'workspace': str(workspace), 'head': git(['rev-parse', 'HEAD'], workspace)}
        board = self.config.runtime / 'kanban'
        board.mkdir()
        with sqlite3.connect(board / 'kanban.db') as db:
            db.execute('CREATE TABLE tasks(id TEXT, workspace_path TEXT, result TEXT)')
            db.execute('INSERT INTO tasks VALUES(?,?,?)', (task['id'], str(workspace), json.dumps({'result':result})))
        runtime = self.config.runtime
        home = runtime / 'native/account'
        memory = home / 'memories'
        memory.mkdir(parents=True)
        (memory / 'MEMORY.md').write_text('Persistent memory')
        (home / '.api-key').write_text('local-service-identity')
        home_channel = {'platform': 'feishu', 'chat_id': 'test-chat', 'name': 'Test home',
                        'thread_id': 'test-thread', 'user_id': 'test-user', 'scope_id': 'test-scope'}
        (home / '.env').write_text("FEISHU_HOME_CHANNEL='test-chat'\n")
        (home / 'config.yaml').write_text(json.dumps({'model': {'default': 'retained'},
            'platforms': {'feishu': {'home_channel': home_channel}},
            'providers': {'local': {'api_key': 'external-secret', 'key_env': 'MY_MODEL_KEY'}},
            'terminal': {'cwd': str(home / 'workspace')}}))
        engineering = runtime / 'engineering' / task['id']
        engineering.mkdir(parents=True)
        (engineering / 'memories').symlink_to(memory)
        cron = runtime / 'scheduler/cron'
        cron.mkdir(parents=True)
        (cron / 'jobs.json').write_text('{"jobs": []}')
        script = Path(result['workspace']) / 'script.sh'
        script.write_text('#!/bin/sh\nexit 0\n')
        script.chmod(0o755)
        cache_source = script.parent / 'cache/source.py'
        cache_source.parent.mkdir()
        cache_source.write_text('CACHE_IMPLEMENTATION = True\n')
        with sqlite3.connect(home / 'state.db') as db, sqlite3.connect(script.parent / 'fixture.db') as fixture:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE messages(text)')
            db.execute("INSERT INTO messages VALUES('committed WAL data')")
            db.execute('CREATE TABLE gateway_routing(scope TEXT, session_key TEXT, entry_json TEXT, PRIMARY KEY(scope, session_key))')
            routing = json.dumps({'session_id': 'existing-session', 'history_path': str(home / 'old-history')})
            db.execute('INSERT INTO gateway_routing VALUES(?,?,?)', (str(home / 'sessions'), 'weixin-owner', routing))
            db.execute('INSERT INTO gateway_routing VALUES(?,?,?)', ('/external/sessions', 'unmanaged', routing))
            db.commit()
            fixture.execute('PRAGMA journal_mode=WAL')
            fixture.execute('CREATE TABLE sample(value)')
            fixture.execute('INSERT INTO sample VALUES(42)')
            fixture.commit()
            fixture_bytes = (script.parent / 'fixture.db').read_bytes()
            backup = self.snapshot()
            copied_fixture = backup / script.parent.relative_to(runtime) / 'fixture.db'
            self.assertEqual(copied_fixture.read_bytes(), fixture_bytes)
            self.assertTrue(copied_fixture.with_name('fixture.db-wal').exists())
        restored = self.path / 'restored'
        restore_state(self.config, backup, restored)
        self.assertEqual((restored / 'native/account/.api-key').read_text(), 'local-service-identity')
        self.assertEqual((restored / 'engineering' / task['id'] / 'memories').resolve(),
                         restored / 'native/account/memories')
        self.assertEqual((restored / 'engineering' / task['id'] / 'memories/MEMORY.md').read_text(), 'Persistent memory')
        with sqlite3.connect(restored / 'native/account/state.db') as db:
            self.assertEqual(db.execute('SELECT text FROM messages').fetchone()[0], 'committed WAL data')
            self.assertEqual(db.execute('SELECT entry_json FROM gateway_routing WHERE scope=? AND session_key=?',
                                       (str(restored / 'native/account/sessions'), 'weixin-owner')).fetchone()[0], routing)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM gateway_routing WHERE scope=?',
                                       (str(home / 'sessions'),)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT entry_json FROM gateway_routing WHERE scope='/external/sessions'").fetchone()[0], routing)
        with sqlite3.connect(backup / 'native/account/state.db') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM gateway_routing WHERE scope=?',
                                       (str(home / 'sessions'),)).fetchone()[0], 1)
        cfg = json.loads((restored / 'native/account/config.yaml').read_text())
        self.assertEqual(cfg['platforms']['feishu']['home_channel'], home_channel)
        self.assertFalse((restored / 'native/account/.env').exists())
        self.assertNotIn('api_key', cfg['providers']['local'])
        self.assertEqual(cfg['providers']['local']['key_env'], 'MY_MODEL_KEY')
        self.assertEqual(cfg['terminal']['cwd'], str(restored / 'native/account/workspace'))
        self.data['runtime'] = str(restored)
        self.write_config()
        with sqlite3.connect(restored / 'kanban/kanban.db') as db:
            copied = json.loads(db.execute('SELECT result FROM tasks').fetchone()[0])['result']
        workspace = Path(copied['workspace'])
        self.assertTrue(workspace.is_relative_to(restored))
        self.assertEqual(git(['rev-parse', 'HEAD'], workspace), result['head'])
        self.assertEqual((workspace / 'script.sh').stat().st_mode & 0o777, 0o700)
        self.assertEqual((workspace / 'cache/source.py').read_text(), cache_source.read_text())
        with sqlite3.connect(workspace / 'fixture.db') as fixture:
            self.assertEqual(fixture.execute('SELECT value FROM sample').fetchone()[0], 42)
        self.assertTrue((restored / 'scheduler/cron/jobs.json').exists())
        self.assertEqual(restored.stat().st_mode & 0o777, 0o700)

    def test_credentials_transients_and_external_links(self):
        home = self.config.runtime / 'native/account'
        home.mkdir(parents=True)
        for name in ('.env', '.env.local', 'auth.json', 'tokens.json', 'gateway.log', 'test.pyc'):
            (home / name).write_text('private-test-data')
        backup = self.snapshot()
        self.assertEqual(list((backup / 'native/account').iterdir()), [])
        (home / 'outside').symlink_to(self.repo)
        with self.assertRaisesRegex(MikasaError, '外部符号链接'):
            backup_state(self.config, self.path / 'invalid')
        self.assertFalse((self.path / 'invalid').exists())

    def test_active_runtime_and_old_profile_refuse_backup(self):
        with runtime_lock(self.config.runtime):
            with self.assertRaises(Conflict):
                self.snapshot()
        home = self.config.runtime / 'native/account'
        home.mkdir(parents=True)
        with (home / 'mikasa.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(Conflict):
                self.snapshot()
        self.assertFalse((self.path / 'backup').exists())
        with runtime_lock(self.config.runtime, exclusive=True):
            with self.assertRaises(Conflict):
                self.store.pause(True, 'test')
            with self.assertRaises(Conflict):
                NativeGateway(self.config, self.config.owner)

    def test_failed_gateway_initialization_releases_maintenance_lock(self):
        with patch('mikasa.native.profile_home', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                NativeGateway(self.config, self.config.owner)
        with runtime_lock(self.config.runtime, exclusive=True):
            pass

    def test_tampering_paths_links_and_partial_restore_fail_without_target(self):
        backup = self.snapshot()
        marker = backup / 'manifest.json'
        original = marker.read_text()
        restored = self.path / 'restored'
        for name, entry in (('../escape', {'directory': True}),
                            ('native/bad', {'link': '/outside'}),
                            ('kanban/kanban.db/nested', {'directory': True})):
            manifest = json.loads(original)
            manifest['entries'][name] = entry
            marker.write_text(json.dumps(manifest))
            with self.assertRaises(MikasaError):
                restore_state(self.config, backup, restored)
            self.assertFalse(restored.exists())
        marker.write_text(original)
        with patch('mikasa.backup.native_copy', side_effect=MikasaError('copy failure')):
            with self.assertRaises(MikasaError):
                restore_state(self.config, backup, restored)
        self.assertFalse(restored.exists())
        with (backup / 'mikasa.sqlite3').open('ab') as stream:
            stream.write(b'tampered')
        with self.assertRaisesRegex(MikasaError, '校验失败'):
            restore_state(self.config, backup, restored)
        self.assertFalse(restored.exists())

    def test_existing_destination_and_nested_backup_are_rejected(self):
        with self.assertRaises(MikasaError):
            backup_state(self.config, self.config.runtime / 'backup')
        backup = self.snapshot()
        with self.assertRaises(MikasaError):
            restore_state(self.config, backup, self.config.runtime)
