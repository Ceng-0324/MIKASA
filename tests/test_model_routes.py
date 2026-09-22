import json
import os
from unittest.mock import patch

from mikasa.cli import doctor
from mikasa.errors import MikasaError
from mikasa.model_settings import model_environment, select_source, validate_routes
from tests.support import BaseTest


class ModelRouteTests(BaseTest):
    def setUp(self):
        super().setUp()
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


    def test_missing_claude_source_never_falls_back_to_gpt_credentials(self):
        self.claude.unlink()
        with self.assertRaises(MikasaError):
            model_environment(self.settings, 'claude-test')
        self.assertEqual(model_environment(self.settings, 'gpt-test')['MIKASA_MODEL_API_KEY'], 'gpt-secret')

    def test_claude_source_does_not_resolve_aliases_oauth_or_helpers(self):
        settings = {'model_source': self.settings['model_routes'][0]['model_source']}
        with self.assertRaisesRegex(MikasaError, '完整模型'):
            model_environment(settings)
        self.claude.write_text(json.dumps({'model': 'claude-test', 'apiKeyHelper': 'echo secret',
                                         'env': {'ANTHROPIC_BASE_URL': 'https://cch.invalid'}}))
        with self.assertRaises(MikasaError):
            model_environment(settings)


    def test_model_diagnostics_use_selected_protocol_without_probe(self):
        with patch('mikasa.cli.run_model_probe') as call:
            report = doctor(self.config, selected_model='claude-test')
            call.assert_not_called()
        self.assertEqual(report['model']['source'], 'claude')
        self.assertEqual(report['model']['api_mode'], 'anthropic_messages')
