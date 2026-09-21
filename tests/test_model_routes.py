import json
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from mikasa.chat import Chat
from mikasa.cli import doctor
from mikasa.errors import MikasaError
from mikasa.model_settings import model_environment, select_source, validate_routes
from mikasa.worker import Worker
from tests.support import BaseTest, command_reply


class ModelRouteTests(BaseTest):
    def setUp(self):
        super().setUp()
        adapter = patch.object(Worker, "command", side_effect=command_reply)
        adapter.start()
        self.addCleanup(adapter.stop)
        self.codex = self.path / 'codex.toml'
        self.auth = self.path / 'auth.json'
        self.claude = self.path / 'claude.json'
        self.codex.write_text('model="gpt-test"\nmodel_provider="cch"\n[model_providers.cch]\nbase_url="https://cch.invalid/v1"\nwire_api="responses"\n')
        self.auth.write_text(json.dumps({'OPENAI_API_KEY': 'gpt-secret'}))
        self.claude.write_text(json.dumps({'model': 'opus[1m]', 'env': {
            'ANTHROPIC_BASE_URL': 'https://cch.invalid', 'ANTHROPIC_AUTH_TOKEN': 'claude-secret'},
            'apiKeyHelper': 'must never execute'}))
        self.settings = self.config.data['worker']
        self.settings['model_source'] = {'type': 'codex', 'config_path': str(self.codex)}
        self.settings['model_routes'] = [{'models': ['claude-test'], 'prefixes': ['claude-', 'anthropic/claude-'],
                                         'model_source': {'type': 'claude', 'config_path': str(self.claude)}}]

    def test_protocol_and_credentials_switch_together_and_default_is_unchanged(self):
        before = [p.read_bytes() for p in (self.codex, self.auth, self.claude)]
        with patch.dict(os.environ, {'ANTHROPIC_AUTH_TOKEN': 'foreign-secret', 'MIKASA_MODEL_API_KEY': 'foreign-secret'}):
            gpt = model_environment(self.settings, 'gpt-test')
            claude = model_environment(self.settings, 'claude-test')
        self.assertEqual(gpt['MIKASA_MODEL_API_MODE'], 'codex_responses')
        self.assertEqual(gpt['MIKASA_MODEL_API_KEY'], 'gpt-secret')
        self.assertEqual(claude['MIKASA_MODEL_API_MODE'], 'anthropic_messages')
        self.assertEqual(claude['MIKASA_MODEL_API_KEY'], 'claude-secret')
        self.assertEqual(claude['MIKASA_MODEL_BASE_URL'], 'https://cch.invalid')
        self.assertEqual(model_environment(self.settings)['MIKASA_MODEL'], 'gpt-test')
        self.assertEqual(before, [p.read_bytes() for p in (self.codex, self.auth, self.claude)])

    def test_exact_then_longest_prefix_and_duplicate_rejection(self):
        special = {'type': 'environment'}
        self.settings['model_routes'].append({'models': ['claude-exact'], 'prefixes': ['claude-special-'], 'model_source': special})
        self.assertEqual(select_source(self.settings, 'claude-exact'), special)
        self.assertEqual(select_source(self.settings, 'claude-special-new'), special)
        self.assertEqual(select_source(self.settings, 'claude-new')['type'], 'claude')
        self.assertEqual(select_source(self.settings, 'gpt-new')['type'], 'codex')
        bad_routes = [None, [{}], [{'models': ['x'], 'model_source': {'type': 'claude', 'token': 'secret'}}],
                      [self.settings['model_routes'][0]] * 2]
        for routes in bad_routes:
            with self.subTest(routes=routes), self.assertRaises(MikasaError):
                validate_routes(routes)

    def test_environment_routes_forward_only_selected_credentials_to_worker(self):
        from mikasa.model_settings import MODEL_FIELDS
        mappings = {name: {key: name.upper() + '_' + key for key in MODEL_FIELDS}
                    for name in ('gpt', 'claude')}
        env = {}
        for name, mode in [('gpt', 'codex_responses'), ('claude', 'anthropic_messages')]:
            env.update(dict(zip(mappings[name].values(),
                                [name + '-test', 'https://' + name + '.invalid', name + '-secret', mode])))
        self.settings.update(model_source={'type': 'environment', 'env': mappings['gpt']},
                             model_routes=[{'models': ['claude-test'],
                                            'model_source': {'type': 'environment', 'env': mappings['claude']}}],
                             env_allowlist=list(env))
        seen = []
        def run(*args, **kwargs):
            child = kwargs['env']
            self.assertFalse(set(env) & set(child))
            seen.append((child['MIKASA_MODEL'], child['MIKASA_MODEL_API_KEY'], child['MIKASA_MODEL_API_MODE']))
            return {'code': 0, 'stdout': json.dumps({'version': 1, 'runtime': {'backend': 'fixture'}, 'result': {'summary': 'ok'}})}
        with patch.dict(os.environ, env, clear=True), patch('mikasa.worker.run', side_effect=run):
            for model in ('gpt-test', 'claude-test'):
                Worker(self.config).execute({'payload': {'kind': 'chat'}}, {}, lambda: False, model=model)
        self.assertEqual(seen, [('gpt-test', 'gpt-secret', 'codex_responses'),
                                ('claude-test', 'claude-secret', 'anthropic_messages')])

    def test_missing_claude_source_never_falls_back_to_gpt_credentials(self):
        self.claude.unlink()
        with patch('mikasa.worker.run') as run, self.assertRaises(MikasaError):
            Worker(self.config).execute({'payload': {'kind': 'chat'}}, {}, lambda: False, model='claude-test')
        run.assert_not_called()
        self.assertEqual(model_environment(self.settings, 'gpt-test')['MIKASA_MODEL_API_KEY'], 'gpt-secret')

    def test_claude_source_does_not_resolve_aliases_oauth_or_helpers(self):
        settings = {'model_source': self.settings['model_routes'][0]['model_source']}
        with self.assertRaisesRegex(MikasaError, '完整模型'):
            model_environment(settings)
        self.claude.write_text(json.dumps({'model': 'claude-test', 'apiKeyHelper': 'echo secret',
                                         'env': {'ANTHROPIC_BASE_URL': 'https://cch.invalid'}}))
        with self.assertRaises(MikasaError):
            model_environment(settings)

    def test_parallel_requests_do_not_mix_route_credentials(self):
        seen = []
        def run(*args, **kwargs):
            env = kwargs['env']
            seen.append((env['MIKASA_MODEL'], env['MIKASA_MODEL_API_KEY'], env['MIKASA_MODEL_API_MODE']))
            return {'code': 0, 'stdout': json.dumps({'version': 1, 'runtime': {'backend': 'fixture'}, 'result': {'summary': 'ok'}})}
        def execute(model):
            return Worker(self.config).execute({'payload': {'kind': 'chat'}}, {}, lambda: False, model=model)
        with patch('mikasa.worker.run', side_effect=run), ThreadPoolExecutor(2) as pool:
            list(pool.map(execute, ['gpt-test', 'claude-test'] * 5))
        self.assertEqual(set(seen), {('gpt-test', 'gpt-secret', 'codex_responses'), ('claude-test', 'claude-secret', 'anthropic_messages')})

    def test_model_menu_and_switch_use_native_boundary(self):
        from tests.native_support import Gateways
        gateways = Gateways()
        chat = Chat(self.config, gateways)
        session = chat.create(self.config.owner)
        def send(message, key):
            return chat.send(session['id'], self.config.owner, message, key)
        menu = send('/model', 'menu')
        self.assertEqual(menu['model_options'], ['claude-test'])
        self.assertNotIn('secret', menu['reply'])
        send('记住代号蓝鲸', 'before')
        switched = send('/model claude-test', 'switch')
        self.assertEqual(switched['model'], 'claude-test')
        send('代号是什么', 'after')
        self.assertEqual(gateways.for_actor(self.config.owner).calls[-1]['model'], 'claude-test')
        self.assertIn('蓝鲸', chat.get(session['id'], self.config.owner)['turns'][0]['message'])
        self.assertEqual(send('/model default', 'reset')['model'], 'gpt-test')
        self.assertEqual(chat.create(self.config.owner)['model'], 'gpt-test')
        with patch.object(Worker, 'execute') as call:
            report = doctor(self.config, selected_model='claude-test')
            call.assert_not_called()
        self.assertEqual(report['model']['source'], 'claude')
        self.assertEqual(report['model']['api_mode'], 'anthropic_messages')

    def test_unimplemented_system_commands_never_reach_model(self):
        from tests.native_support import Gateways
        chat = Chat(self.config, Gateways())
        session = chat.create(self.config.owner)
        with patch.object(Worker, 'execute') as call:
            for message in ['/init', '/unknown value']:
                result = chat.send(session['id'], self.config.owner, message, message)
                self.assertEqual(result['kind'], 'deferred_command' if message == '/init' else 'unsupported_command')
            call.assert_not_called()
