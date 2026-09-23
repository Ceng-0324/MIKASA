import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mikasa.config import Config
from mikasa.errors import Forbidden, MikasaError
from mikasa.native import HERMES_REVISION, prepare_profile
from tests.support import ROOT


class NativeProfileTests(unittest.TestCase):
    def test_compression_refresh_preserves_native_routes_thresholds_and_opt_out(self):
        for engineering in (False, True):
            with self.subTest(engineering=engineering):
                home, *_ = prepare_profile(self.config, self.config.owner, engineering=engineering)
                path = home / 'config.yaml'
                current = json.loads(path.read_text())
                current['compression'] = {'enabled': True, 'threshold_tokens': 180000}
                current['auxiliary'] = {'compression': {
                    'provider': 'operator-primary', 'model': 'summary-model',
                    'fallback_chain': [{'provider': 'operator-backup', 'model': 'backup-model'}]}}
                path.write_text(json.dumps(current))
                prepare_profile(self.config, self.config.owner, engineering=engineering)
                updated = json.loads(path.read_text())
                self.assertEqual(updated['compression'], {**current['compression'], 'progress_notices': True})
                self.assertEqual(updated['auxiliary'], current['auxiliary'])
                updated['compression']['progress_notices'] = False
                path.write_text(json.dumps(updated))
                prepare_profile(self.config, self.config.owner, engineering=engineering)
                self.assertEqual(json.loads(path.read_text()), updated)

    def test_progress_restore_is_once_and_keeps_platform_preferences(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        current = json.loads(path.read_text())
        current['_mikasa_progress_defaults'] = 1
        current['display']['tool_progress'] = 'new'
        current['display']['platforms']['feishu'] = {'tool_progress': 'off'}
        current['display'].pop('background_process_notifications')
        current['agent']['gateway_notify_interval'] = 60
        path.write_text(json.dumps(current))
        prepare_profile(self.config, self.config.owner)
        updated = json.loads(path.read_text())
        self.assertEqual(updated['display']['tool_progress'], 'all')
        self.assertEqual(updated['display']['background_process_notifications'], 'error')
        self.assertEqual(updated['display']['platforms'], current['display']['platforms'])
        self.assertEqual(updated['agent']['gateway_notify_interval'], 15)
        updated['display']['tool_progress'] = 'new'
        updated['agent']['gateway_notify_interval'] = 60
        path.write_text(json.dumps(updated))
        prepare_profile(self.config, self.config.owner)
        self.assertEqual(json.loads(path.read_text()), updated)

    def test_release_skill_roots_replace_managed_paths_preserving_user_skills(self):
        from workers.hermes.profile_config import merge
        home, *_ = prepare_profile(self.config, self.config.owner)
        generated = json.loads((home / 'config.yaml').read_text())
        old = json.loads(json.dumps(generated))
        old['skills']['external_dirs'] = ['/opt/mikasa/skills',
            '/opt/mikasa-releases/legacy-1790075750/skills',
            '/opt/mikasa-releases/' + 'a' * 40 + '/skills', '/home/mikasa/custom-skills']
        generated['skills']['external_dirs'] = ['/opt/mikasa-releases/' + 'b' * 40 + '/skills']
        refreshed = merge(old, generated)
        self.assertEqual(refreshed['skills']['external_dirs'],
            generated['skills']['external_dirs'] + ['/home/mikasa/custom-skills'])
        generated['skills']['external_dirs'] = ['/some/new/install/skills']
        reverted = merge(refreshed, generated)
        self.assertEqual(reverted['skills']['external_dirs'],
            ['/some/new/install/skills', '/home/mikasa/custom-skills'])
        self.assertEqual(reverted['model'], old['model'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-unit-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        source = self.path/'hermes'
        (source/'gateway').mkdir(parents=True)
        (source/'gateway/run.py').write_text('# synthetic fixture\n')
        (source/'.mikasa-source.json').write_text(json.dumps({'repository':'NousResearch/hermes-agent', 'revision':HERMES_REVISION, 'verified_git_blobs':1}))
        data = json.loads((ROOT/'config/examples/mikasa.json').read_text())
        data.update(runtime=str(self.path/'state'), members=['human'])
        data['worker'].update(hermes_source=str(source), native_python=sys.executable)
        self.config = Config(ROOT, data)
        self.env = patch.dict(os.environ, {'MIKASA_MODEL':'fixture-model','MIKASA_MODEL_BASE_URL':'https://cch.invalid/v1','MIKASA_MODEL_API_KEY':'sensitive-fixture-key', 'MIKASA_MODEL_API_MODE':'codex_responses'})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_native_regeneration_preserves_memory_and_session(self):
        home, _, _, credentials = prepare_profile(self.config, self.config.owner)
        (home/'memories').mkdir()
        (home/'memories/MEMORY.md').write_text('user fact')
        (home/'memories/USER.md').write_text('confirmed collaboration preference')
        (home/'state.db').write_bytes(b'existing-native-database')
        prepare_profile(self.config, self.config.owner)
        self.assertEqual((home/'memories/MEMORY.md').read_text(), 'user fact')
        self.assertEqual((home/'memories/USER.md').read_text(), 'confirmed collaboration preference')
        self.assertEqual((home/'state.db').read_bytes(), b'existing-native-database')
        self.assertIn('sensitive-fixture-key', credentials.values())
        self.assertFalse(any(b'sensitive-fixture-key' in p.read_bytes() for p in home.rglob('*') if p.is_file()))
        config = json.loads((home/'config.yaml').read_text())
        self.assertEqual(config['skills']['auto_load'], ['mikasa-persona'])
        self.assertNotIn('platform_toolsets', config)
        self.assertEqual(config['agent'], {'gateway_notify_interval': 15})
        self.assertEqual((home/'SOUL.md').read_bytes(), (ROOT/'identity.md').read_bytes())

    def test_unchanged_bootstrap_does_not_replace_native_files(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        # Native JSON is also valid YAML; preserve the operator's formatting.
        path.write_text(json.dumps(json.loads(path.read_text()), indent=4) + '\n')
        files = [path, home / 'SOUL.md', home / 'policy/actor.json']
        before = [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in files]
        prepare_profile(self.config, self.config.owner)
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in files])

    def test_existing_display_gets_missing_defaults_without_resetting_choices(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        native = json.loads(path.read_text())
        native['display'].pop('interim_assistant_messages')
        native['display'].pop('long_running_notifications')
        native['display']['platforms']['feishu'] = {'tool_progress': 'off'}
        path.write_text(json.dumps(native))
        prepare_profile(self.config, self.config.owner)
        refreshed = json.loads(path.read_text())
        self.assertTrue(refreshed['display']['interim_assistant_messages'])
        self.assertTrue(refreshed['display']['long_running_notifications'])
        self.assertEqual(refreshed['display']['platforms'], native['display']['platforms'])
        refreshed['display']['interim_assistant_messages'] = False
        path.write_text(json.dumps(refreshed))
        prepare_profile(self.config, self.config.owner)
        self.assertEqual(json.loads(path.read_text()), refreshed)

    def test_actor_home_and_memory_isolation_and_authorization(self):
        owner, *_ = prepare_profile(self.config, self.config.owner)
        human, *_ = prepare_profile(self.config, 'human')
        self.assertNotEqual(owner, human)
        self.assertEqual(json.loads((human/'policy/actor.json').read_text())['actor'], 'human')
        with self.assertRaises(Forbidden):
            prepare_profile(self.config, 'unknown')

    def test_environment_routes_generate_distinct_native_providers_without_disk_keys(self):
        from mikasa.native import provider_id
        from mikasa.model_settings import MODEL_FIELDS
        mapping = {key: 'CLAUDE_' + key for key in MODEL_FIELDS}
        source = {'type': 'environment', 'env': mapping}
        self.config.data['worker']['model_routes'] = [{'models': ['claude-test'], 'model_source': source}]
        self.config.data['worker']['env_allowlist'].extend(mapping.values())
        env = dict(zip(mapping.values(), ['claude-test', 'https://claude.invalid',
                                         'claude-private-key', 'anthropic_messages']))
        with patch.dict(os.environ, env):
            home, _, _, credentials = prepare_profile(self.config, self.config.owner)
        native = json.loads((home/'config.yaml').read_text())
        gpt = native['providers'][native['model']['provider']]
        claude = native['providers'][provider_id(source)]
        self.assertEqual(gpt['api_mode'], 'codex_responses')
        self.assertEqual(claude['api_mode'], 'anthropic_messages')
        self.assertEqual(credentials[claude['key_env']], 'claude-private-key')
        self.assertEqual(native['model_aliases']['claude-test']['provider'], provider_id(source))
        self.assertFalse(any(b'claude-private-key' in p.read_bytes() for p in home.rglob('*') if p.is_file()))

    def test_messaging_policy_distinguishes_profile_owner_from_message_sender(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from workers.hermes.plugin import register
        self.config.data['feishu'] = {'owner_open_id': 'ou_owner', 'owner_user_id': 'owner_tenant_id'}
        home, *_ = prepare_profile(self.config, self.config.owner)
        context = Mock()
        with patch.dict(sys.modules, {'hermes_constants': SimpleNamespace(get_hermes_home=lambda: home)}):
            register(context)
        prompt = ''.join(call.args[1] for call in context.register_system_prompt_section.call_args_list)
        self.assertNotIn('当前已鉴权账号', prompt)
        self.assertIn('共用 profile 不代表是同一人', prompt)
        self.assertIn(self.config.owner + ' 对应 ou_owner, owner_tenant_id', prompt)
        self.assertIn('仅说明身份，不限制其他人聊天', prompt)

    def test_weixin_owner_identity_uses_validated_user_not_bot_or_token(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from workers.hermes.plugin import register
        from mikasa.native import private_write
        binding = self.config.runtime / 'credentials/weixin.json'
        value = {'actor': self.config.owner, 'account_id': 'bot@im.bot',
                 'user_id': 'owner@im.wechat', 'token': 'private-weixin-token',
                 'base_url': 'https://ilinkai.weixin.qq.com'}
        private_write(binding, json.dumps(value))
        home, *_ = prepare_profile(self.config, self.config.owner)
        identity = json.loads((home/'policy/actor.json').read_text())
        self.assertEqual(identity['weixin_owner'], {'account': self.config.owner, 'user_id': value['user_id']})
        context = Mock()
        with patch.dict(sys.modules, {'hermes_constants': SimpleNamespace(get_hermes_home=lambda: home)}):
            register(context)
        prompt = ''.join(call.args[1] for call in context.register_system_prompt_section.call_args_list)
        self.assertIn('微信发送者 ID owner@im.wechat 对应主人 ' + self.config.owner, prompt)
        self.assertIn('仅在微信发送者 ID 匹配时适用', prompt)
        self.assertNotIn(value['account_id'], prompt)
        self.assertFalse(any(value['token'].encode() in p.read_bytes() for p in home.rglob('*') if p.is_file()))
        private_write(binding, json.dumps({**value, 'actor': 'stranger'}))
        before = (home/'policy/actor.json').read_bytes()
        with self.assertRaises(MikasaError):
            prepare_profile(self.config, self.config.owner)
        self.assertEqual((home/'policy/actor.json').read_bytes(), before)
        binding.unlink()
        prepare_profile(self.config, self.config.owner)
        self.assertNotIn('weixin_owner', json.loads((home/'policy/actor.json').read_text()))

    def test_refresh_preserves_native_preferences_and_refreshes_integration_routes(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        native = json.loads(path.read_text())
        native['model'].update(default='native-selected', reasoning_effort='high')
        native['display'] = {'compact': True}
        provider = next(iter(native['providers']))
        native['providers'][provider]['base_url'] = 'https://stale.invalid'
        native['skills']['auto_load'].append('user-skill')
        path.write_text(json.dumps(native))
        prepare_profile(self.config, self.config.owner)
        refreshed = json.loads(path.read_text())
        self.assertEqual(refreshed['model'], native['model'])
        self.assertTrue(refreshed['display']['compact'])
        self.assertEqual(refreshed['skills']['auto_load'], ['mikasa-persona', 'user-skill'])
        self.assertEqual(refreshed['providers'][provider]['base_url'], 'https://cch.invalid/v1')

    def test_bad_native_config_is_not_overwritten(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        original = '["not a mapping"]'
        path.write_text(original)
        with self.assertRaisesRegex(MikasaError, '原有配置保留'):
            prepare_profile(self.config, self.config.owner)
        self.assertEqual(path.read_text(), original)

    def test_refresh_removes_obsolete_managed_routes_but_keeps_native_routes(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        native = json.loads(path.read_text())
        native['providers'].update({'cch-0000000000000000': {'base_url': 'https://old.invalid'},
                                    'local-user': {'base_url': 'http://localhost:1234'}})
        native['model_aliases'].update({'old-model': {'provider': 'cch-0000000000000000'},
                                       'user-alias': {'provider': 'local-user', 'model': 'local'}})
        path.write_text(json.dumps(native))
        prepare_profile(self.config, self.config.owner)
        refreshed = json.loads(path.read_text())
        self.assertNotIn('cch-0000000000000000', refreshed['providers'])
        self.assertNotIn('old-model', refreshed['model_aliases'])
        self.assertEqual(refreshed['providers']['local-user'], native['providers']['local-user'])
        self.assertEqual(refreshed['model_aliases']['user-alias'], native['model_aliases']['user-alias'])

    def test_removed_selected_provider_does_not_silently_reset_native_preference(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        native = json.loads(path.read_text())
        native['model']['provider'] = 'cch-0000000000000000'
        original = json.dumps(native)
        path.write_text(original)
        with self.assertRaisesRegex(MikasaError, '所选 CCH provider'):
            prepare_profile(self.config, self.config.owner)
        self.assertEqual(path.read_text(), original)

    def test_native_launcher_inherits_tty_but_not_unrelated_credentials(self):
        from mikasa.native import interactive
        from unittest.mock import Mock
        process = Mock()
        process.wait.return_value = 0
        process.poll.return_value = 0
        prepared = prepare_profile(self.config, self.config.owner)
        with patch.dict(os.environ, {'GH_TOKEN': 'private', 'OPENAI_API_KEY': 'unrelated'}), \
                patch('mikasa.native.prepare_profile', return_value=prepared), \
                patch('mikasa.native.subprocess.Popen', return_value=process) as spawn:
            self.assertEqual(interactive(self.config, 'native-session'), 0)
        args, kwargs = spawn.call_args
        self.assertEqual(args[0][-2:], ['--resume', 'native-session'])
        self.assertNotIn('stdin', kwargs)
        self.assertNotIn('stdout', kwargs)
        self.assertNotIn('GH_TOKEN', kwargs['env'])
        self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
        self.assertIn('sensitive-fixture-key', kwargs['env'].values())
        self.assertFalse((self.config.runtime / 'mikasa.sqlite3').exists())

    def test_native_cli_cannot_mutate_profile_during_initialization(self):
        import fcntl
        from mikasa.native import interactive
        from mikasa.errors import Conflict
        home, *_ = prepare_profile(self.config, self.config.owner)
        before = (home / 'config.yaml').read_bytes()
        with (home / 'mikasa.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(Conflict):
                interactive(self.config)
        self.assertEqual((home / 'config.yaml').read_bytes(), before)

    def test_native_profile_lock_is_released_before_child_runtime(self):
        import fcntl
        from unittest.mock import Mock
        from mikasa.native import interactive
        prepared = prepare_profile(self.config, self.config.owner)
        process = Mock()
        process.wait.return_value = 0
        process.poll.return_value = 0

        def spawn(*args, **kwargs):
            with (prepared[0] / 'mikasa.lock').open('a') as other:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            from mikasa.maintenance import runtime_lock
            from mikasa.errors import Conflict
            with self.assertRaises(Conflict), runtime_lock(self.config.runtime, exclusive=True):
                pass
            return process

        with patch('mikasa.native.prepare_profile', return_value=prepared), \
                patch('mikasa.native.subprocess.Popen', side_effect=spawn):
            self.assertEqual(interactive(self.config), 0)

    def test_feishu_launcher_uses_owner_profile_and_never_persists_app_secret(self):
        from mikasa.native import interactive
        from unittest.mock import Mock
        self.config.data['feishu'] = {'domain': 'feishu', 'owner_open_id': 'ou_owner'}
        prepared = prepare_profile(self.config, self.config.owner)
        process = Mock()
        process.wait.return_value = 0
        process.poll.return_value = 0
        with patch.dict(os.environ, {'MIKASA_FEISHU_APP_ID': 'cli_fixture', 'MIKASA_FEISHU_APP_SECRET': 'feishu-secret',
                                     'FEISHU_ALLOW_ALL_USERS': 'false', 'GATEWAY_ALLOW_ALL_USERS': 'true',
                                     'FEISHU_GROUP_POLICY': 'disabled', 'FEISHU_REQUIRE_MENTION': 'true',
                                     'FEISHU_HOME_CHANNEL': 'oc_unwanted', 'GH_TOKEN': 'private'}), \
                patch('mikasa.native.prepare_profile', return_value=prepared), \
                patch('mikasa.native.subprocess.Popen', return_value=process) as spawn:
            self.assertEqual(interactive(self.config, platforms=('feishu',)), 0)
        command = spawn.call_args.args[0]
        env = spawn.call_args.kwargs['env']
        self.assertEqual(Path(command[1]).name, 'native_gateway.py')
        self.assertEqual(command[2], '--config')
        self.assertEqual(env['FEISHU_ALLOWED_USERS'], '')
        self.assertEqual(env['FEISHU_ALLOW_ALL_USERS'], 'true')
        self.assertEqual(env['GATEWAY_ALLOW_ALL_USERS'], 'false')
        self.assertEqual(env['FEISHU_GROUP_POLICY'], 'open')
        self.assertEqual(env['FEISHU_ALLOW_BOTS'], 'all')
        self.assertEqual(env['FEISHU_REQUIRE_MENTION'], 'false')
        self.assertNotIn('FEISHU_HOME_CHANNEL', env)
        self.assertNotIn('GH_TOKEN', env)
        self.assertFalse(any(b'feishu-secret' in p.read_bytes() for p in prepared[0].rglob('*') if p.is_file()))
        native = json.loads((prepared[0] / 'config.yaml').read_text())
        self.assertNotIn('platform_toolsets', native)
        self.assertEqual(native['skills']['auto_load'], ['mikasa-persona'])
        self.assertEqual(json.loads((prepared[0] / 'policy/actor.json').read_text())['actor'], self.config.owner)

    def test_feishu_cannot_mutate_profile_during_initialization(self):
        import fcntl
        from mikasa.native import interactive
        from mikasa.errors import Conflict
        self.config.data['feishu'] = {'owner_open_id': 'ou_owner'}
        home, *_ = prepare_profile(self.config, self.config.owner)
        with (home / 'mikasa.lock').open('a') as lock, \
                patch.dict(os.environ, {'MIKASA_FEISHU_APP_ID': 'cli_fixture', 'MIKASA_FEISHU_APP_SECRET': 'feishu-secret'}), \
                patch('mikasa.native.subprocess.Popen') as spawn:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(Conflict):
                interactive(self.config, platforms=('feishu',))
        spawn.assert_not_called()
        self.assertFalse((home / 'gateway-messaging.json').exists())

    def test_concurrent_gateway_launches_keep_separate_binding_files(self):
        from mikasa.native import interactive
        from unittest.mock import Mock
        self.config.data['feishu'] = {'owner_open_id': 'ou_owner'}
        prepared = prepare_profile(self.config, self.config.owner)
        paths = []

        def spawn(command, **kwargs):
            path = Path(command[-1])
            paths.append(path)
            child = Mock()
            child.poll.return_value = 0
            child.wait.return_value = 0
            if len(paths) == 1:
                def wait():
                    content = path.read_bytes()
                    self.assertEqual(interactive(self.config, platforms=('feishu',)), 0)
                    self.assertNotEqual(paths[0], paths[1])
                    self.assertEqual(path.read_bytes(), content)
                    self.assertFalse(paths[1].exists())
                    return 0
                child.wait.side_effect = wait
            return child

        with patch.dict(os.environ, {'MIKASA_FEISHU_APP_ID': 'cli_fixture', 'MIKASA_FEISHU_APP_SECRET': 'secret'}), \
                patch('mikasa.native.prepare_profile', return_value=prepared), \
                patch('mikasa.native.subprocess.Popen', side_effect=spawn):
            self.assertEqual(interactive(self.config, platforms=('feishu',)), 0)
        self.assertFalse(any(p.parent.exists() for p in paths))

    def test_multiple_platforms_use_one_native_process_without_persisting_bot_token(self):
        from mikasa.native import interactive, private_write
        from unittest.mock import Mock
        self.config.data['feishu'] = {'owner_open_id': 'ou_owner'}
        private_write(self.config.runtime / 'credentials/weixin.json', json.dumps({
            'actor': self.config.owner, 'account_id': 'bot@im.bot', 'user_id': 'owner@im.wechat',
            'token': 'private-weixin-token', 'base_url': 'https://ilinkai.weixin.qq.com'}))
        prepared = prepare_profile(self.config, self.config.owner)
        process = Mock()
        process.wait.return_value = process.poll.return_value = 0
        captured = []
        def spawn(*args, **kwargs):
            path = Path(args[0][args[0].index('--config') + 1])
            captured.append((path, json.loads(path.read_text())))
            return process
        with patch.dict(os.environ, {'MIKASA_FEISHU_APP_ID': 'cli_fixture', 'MIKASA_FEISHU_APP_SECRET': 'secret',
                                     'WEIXIN_ALLOW_ALL_USERS': 'true', 'WEIXIN_HOME_CHANNEL': 'stranger'}), \
                patch('mikasa.native.prepare_profile', return_value=prepared), \
                patch('mikasa.native.subprocess.Popen', side_effect=spawn) as spawn_mock:
            self.assertEqual(interactive(self.config, platforms=('feishu', 'weixin')), 0)
        self.assertEqual(spawn_mock.call_count, 1)
        env = spawn_mock.call_args.kwargs['env']
        self.assertEqual(env['HERMES_HOME'], str(prepared[0]))
        self.assertEqual(env['WEIXIN_TOKEN'], 'private-weixin-token')
        self.assertEqual(env['WEIXIN_ALLOW_ALL_USERS'], 'false')
        self.assertEqual(env['FEISHU_ALLOW_ALL_USERS'], 'true')
        self.assertEqual(env['GATEWAY_ALLOW_ALL_USERS'], 'false')
        self.assertNotIn('WEIXIN_HOME_CHANNEL', env)
        gateway_path, gateway = captured[0]
        self.assertNotEqual(gateway_path, prepared[0] / 'gateway-messaging.json')
        self.assertFalse(gateway_path.exists())
        self.assertFalse(gateway_path.parent.exists())
        self.assertEqual(set(gateway['platforms']), {'feishu', 'weixin'})
        self.assertFalse(any(b'private-weixin-token' in p.read_bytes() for p in prepared[0].rglob('*') if p.is_file()))
        native = json.loads((prepared[0] / 'config.yaml').read_text())
        self.assertNotIn('platform_toolsets', native)
        (self.config.runtime / 'credentials/weixin.json').unlink()
        with patch('mikasa.native.prepare_profile') as prepare, patch('mikasa.native.subprocess.Popen') as spawn, \
                self.assertRaises(MikasaError):
            interactive(self.config, platforms=('weixin',))
        prepare.assert_not_called()
        spawn.assert_not_called()

    def test_gateway_command_passes_selected_platforms_to_native_entry(self):
        from mikasa.cli import main
        with patch('mikasa.cli.Config.load', return_value=self.config), \
                patch('mikasa.native.interactive', return_value=0) as interactive:
            self.assertEqual(main(['--config', str(self.path / 'config.json'),
                                   'gateway', '--platform', 'feishu', '--platform', 'weixin']), 0)
        interactive.assert_called_once_with(self.config, platforms=['feishu', 'weixin'])

    def test_native_launcher_terminates_child_and_restores_handler_on_sigterm(self):
        import fcntl
        import signal
        import subprocess
        from unittest.mock import Mock
        from mikasa.native import interactive
        prepared = prepare_profile(self.config, self.config.owner)
        previous = signal.getsignal(signal.SIGTERM)
        process = Mock()
        process.poll.return_value = None
        def wait(timeout=None):
            if timeout:
                raise subprocess.TimeoutExpired('native-cli', timeout)
            if not process.terminate.called:
                signal.raise_signal(signal.SIGTERM)
            return 0
        process.wait.side_effect = wait
        with patch('mikasa.native.prepare_profile', return_value=prepared), \
                patch('mikasa.native.subprocess.Popen', return_value=process):
            with self.assertRaises(SystemExit) as stopped:
                interactive(self.config)
        self.assertEqual(stopped.exception.code, 128 + signal.SIGTERM)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        with (prepared[0] / 'mikasa.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_native_dotenv_preserved(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        (home/'.env').write_text('NATIVE_TOOL_KEY=fixture')
        prepare_profile(self.config, self.config.owner)
        self.assertEqual((home/'.env').read_text(), 'NATIVE_TOOL_KEY=fixture')
    def test_chat_upgrade_preserves_history_and_user_preferences(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        current = json.loads(path.read_text())
        current.pop('_mikasa_native_tools', None)
        current.pop('_mikasa_live_progress', None)
        current.update(platform_toolsets={'cli': ['memory', 'skills', 'session_search'],
                                         'api_server': ['memory', 'skills'],
                                         'feishu': ['memory', 'skills'], 'weixin': ['terminal']},
                       agent={'max_turns': 12, 'reasoning_effort': 'high'},
                       gateway={'api_server': {'max_concurrent_runs': 1, 'port': 9000},
                                'retired_api_server': {'max_concurrent_runs': 1, 'port': 9000}})
        current['display']['tool_progress'] = 'off'
        path.write_text(json.dumps(current))
        (home/'state.db').write_bytes(b'existing-history')
        prepare_profile(self.config, self.config.owner)
        migrated = json.loads(path.read_text())
        self.assertEqual(migrated['platform_toolsets'], {'weixin': ['terminal']})
        self.assertEqual(migrated['agent'], {'reasoning_effort': 'high', 'gateway_notify_interval': 15})
        self.assertEqual(migrated['gateway']['api_server'], {'port': 9000})
        self.assertEqual(migrated['gateway']['retired_api_server'], {'max_concurrent_runs': 1, 'port': 9000})
        self.assertEqual(migrated['display']['tool_progress'], 'new')
        self.assertEqual((home/'state.db').read_bytes(), b'existing-history')
        migrated['agent']['max_turns'] = 12
        migrated['agent']['gateway_notify_interval'] = 75
        migrated['display']['tool_progress'] = 'off'
        path.write_text(json.dumps(migrated))
        prepare_profile(self.config, self.config.owner)
        self.assertEqual(json.loads(path.read_text()), migrated)

    def test_chat_tool_migration_repairs_v1_without_resetting_preferences(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        path = home / 'config.yaml'
        current = json.loads(path.read_text())
        current['_mikasa_native_tools'] = 1
        current['gateway'] = None
        current['platform_toolsets'] = {'cli': ['memory', 'skills', 'session_search'],
                                       'feishu': ['memory', 'skills'], 'weixin': ['terminal']}
        current['agent']['max_turns'] = 12
        current['display']['tool_progress'] = 'off'
        path.write_text(json.dumps(current))

        prepare_profile(self.config, self.config.owner)

        migrated = json.loads(path.read_text())
        self.assertEqual(migrated['_mikasa_native_tools'], 2)
        self.assertIsNone(migrated['gateway'])
        self.assertEqual(migrated['platform_toolsets'],
                         {'cli': ['memory', 'skills', 'session_search'], 'weixin': ['terminal']})
        self.assertEqual(migrated['agent']['max_turns'], 12)
        self.assertEqual(migrated['display']['tool_progress'], 'off')

    def test_chat_receives_account_home_and_explicit_tool_environment(self):
        from mikasa.native import runtime_environment
        self.config.data['engineering'] = {'env_allowlist': ['EXTERNAL_TOOL_KEY']}
        home, source, python, credentials = prepare_profile(self.config, self.config.owner)
        with patch.dict(os.environ, {'EXTERNAL_TOOL_KEY': 'explicit', 'UNRELATED_KEY': 'private',
                                    'MIKASA_GITHUB_TOKEN': 'account-token', 'HOME': '/home/fixture'}):
            env = runtime_environment(self.config, home, source, python, credentials)
        self.assertEqual(env['HOME'], '/home/fixture')
        self.assertEqual(env['EXTERNAL_TOOL_KEY'], 'explicit')
        self.assertEqual(env['GH_TOKEN'], 'account-token')
        self.assertTrue(env['PATH'].startswith(str(python.parent)))
        self.assertNotIn('UNRELATED_KEY', env)
        self.assertNotIn('HERMES_ENABLE_PROJECT_PLUGINS', env)
