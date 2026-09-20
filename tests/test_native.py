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
        (home/'state.db').write_bytes(b'existing-native-database')
        key = (home/'.api-key').read_bytes()
        prepare_profile(self.config, self.config.owner)
        self.assertEqual((home/'memories/MEMORY.md').read_text(), 'user fact')
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
