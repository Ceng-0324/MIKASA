import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mikasa.config import Config
from mikasa.errors import Forbidden, MikasaError
from mikasa.native import HERMES_REVISION, NativeGateways, prepare_profile
from tests.support import ROOT


class NativeProfileTests(unittest.TestCase):
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

    def test_native_regeneration_preserves_memory_session_and_service_key(self):
        home, _, _, credentials = prepare_profile(self.config, self.config.owner)
        (home/'memories').mkdir()
        (home/'memories/MEMORY.md').write_text('user fact')
        (home/'memories/USER.md').write_text('confirmed collaboration preference')
        (home/'state.db').write_bytes(b'existing-native-database')
        key = (home/'.api-key').read_bytes()
        prepare_profile(self.config, self.config.owner)
        self.assertEqual((home/'memories/MEMORY.md').read_text(), 'user fact')
        self.assertEqual((home/'memories/USER.md').read_text(), 'confirmed collaboration preference')
        self.assertEqual((home/'state.db').read_bytes(), b'existing-native-database')
        self.assertEqual((home/'.api-key').read_bytes(), key)
        self.assertEqual((home/'.api-key').stat().st_mode & 0o777, 0o600)
        self.assertIn('sensitive-fixture-key', credentials.values())
        self.assertFalse(any(b'sensitive-fixture-key' in p.read_bytes() for p in home.rglob('*') if p.is_file()))
        config = json.loads((home/'config.yaml').read_text())
        self.assertEqual(config['skills']['auto_load'], ['mikasa-persona'])
        self.assertEqual(set(config['platform_toolsets']['api_server']), {'memory','skills'})
        self.assertEqual((home/'SOUL.md').read_bytes(), (ROOT/'identity.md').read_bytes())

    def test_actor_home_and_memory_isolation_and_authorization(self):
        owner, *_ = prepare_profile(self.config, self.config.owner)
        human, *_ = prepare_profile(self.config, 'human')
        self.assertNotEqual(owner, human)
        self.assertNotEqual((owner/'.api-key').read_bytes(), (human/'.api-key').read_bytes())
        self.assertEqual(json.loads((human/'policy/actor.json').read_text())['actor'], 'human')
        with self.assertRaises(Forbidden):
            prepare_profile(self.config, 'unknown')

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
        self.assertEqual(refreshed['display'], native['display'])
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

    def test_native_cli_cannot_mutate_an_active_gateway_profile(self):
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
        self.assertEqual(native['platform_toolsets']['feishu'], ['memory', 'skills'])
        self.assertEqual(native['skills']['auto_load'], ['mikasa-persona'])
        self.assertEqual(json.loads((prepared[0] / 'policy/actor.json').read_text())['actor'], self.config.owner)

    def test_feishu_cannot_mutate_an_active_owner_profile(self):
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
        with patch.dict(os.environ, {'MIKASA_FEISHU_APP_ID': 'cli_fixture', 'MIKASA_FEISHU_APP_SECRET': 'secret',
                                     'WEIXIN_ALLOW_ALL_USERS': 'true', 'WEIXIN_HOME_CHANNEL': 'stranger'}), \
                patch('mikasa.native.prepare_profile', return_value=prepared), \
                patch('mikasa.native.subprocess.Popen', return_value=process) as spawn:
            self.assertEqual(interactive(self.config, platforms=('feishu', 'weixin')), 0)
        self.assertEqual(spawn.call_count, 1)
        env = spawn.call_args.kwargs['env']
        self.assertEqual(env['HERMES_HOME'], str(prepared[0]))
        self.assertEqual(env['WEIXIN_TOKEN'], 'private-weixin-token')
        self.assertEqual(env['WEIXIN_ALLOW_ALL_USERS'], 'false')
        self.assertEqual(env['FEISHU_ALLOW_ALL_USERS'], 'true')
        self.assertEqual(env['GATEWAY_ALLOW_ALL_USERS'], 'false')
        self.assertNotIn('WEIXIN_HOME_CHANNEL', env)
        gateway = json.loads((prepared[0] / 'gateway-messaging.json').read_text())
        self.assertEqual(set(gateway['platforms']), {'feishu', 'weixin'})
        self.assertFalse(any(b'private-weixin-token' in p.read_bytes() for p in prepared[0].rglob('*') if p.is_file()))
        native = json.loads((prepared[0] / 'config.yaml').read_text())
        self.assertEqual(native['platform_toolsets']['weixin'], ['memory', 'skills'])
        (self.config.runtime / 'credentials/weixin.json').unlink()
        with patch('mikasa.native.prepare_profile') as prepare, patch('mikasa.native.subprocess.Popen') as spawn, \
                self.assertRaises(MikasaError):
            interactive(self.config, platforms=('weixin',))
        prepare.assert_not_called()
        spawn.assert_not_called()

    def test_legacy_feishu_command_remains_single_platform_compatibility_entry(self):
        from mikasa.cli import main
        with patch('mikasa.cli.Config.load', return_value=self.config), \
                patch('mikasa.native.interactive', return_value=0) as interactive:
            self.assertEqual(main(['--config', str(self.path / 'config.json'), 'feishu']), 0)
        interactive.assert_called_once_with(self.config, platforms=('feishu',))

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

    def test_dotenv_and_unsafe_service_credentials_fail_closed(self):
        home, *_ = prepare_profile(self.config, self.config.owner)
        (home/'.env').write_text('UNEXPECTED_KEY=secret')
        with self.assertRaises(MikasaError):
            prepare_profile(self.config, self.config.owner)
        (home/'.env').unlink()
        (home/'.api-key').chmod(0o644)
        with self.assertRaises(MikasaError):
            prepare_profile(self.config, self.config.owner)

    def test_closed_runtime_cannot_restart_from_late_http_request(self):
        gateways = NativeGateways(self.config)
        gateways.close()
        with self.assertRaises(MikasaError):
            gateways.for_actor(self.config.owner)
