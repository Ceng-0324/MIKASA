import io
import json
import os
from contextlib import redirect_stdout
from unittest.mock import patch

from mikasa.cli import doctor, main
from mikasa.errors import MikasaError
from mikasa.model_settings import model_diagnostics, model_environment, validate_source, validate_environment
from tests.support import BaseTest


class ModelSettingsTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.env = {"MIKASA_MODEL": "model-a", "MIKASA_MODEL_BASE_URL": "https://gateway.invalid/private-path/v1",
                    "MIKASA_MODEL_API_KEY": "fixture-private-key", "MIKASA_MODEL_API_MODE": "codex_responses"}
        self.settings = {"env_allowlist": list(self.env)}

    def test_environment_uses_only_allowlist_and_safe_diagnostic_fields(self):
        with patch.dict(os.environ, self.env, clear=True), patch("pathlib.Path.read_text", side_effect=AssertionError("auth read")):
            self.assertEqual(model_environment({}), {})
            report = model_diagnostics(self.settings)
        self.assertEqual(report["configuration"], "valid")
        self.assertEqual(report["endpoint_origin"], "https://gateway.invalid")
        self.assertEqual(report["connection"], "not_checked")
        self.assertEqual(report["provider_group"], "unverified")
        self.assertNotIn("private", json.dumps(report))

    def test_invalid_config_rejected_before_worker_spawn_without_echo(self):
        self.config.data["worker"].update(self.settings)
        values = {"MIKASA_MODEL_BASE_URL": ["https://user:private@gateway.invalid", "https://gateway.invalid?key=private",
                                           "https://gateway.invalid/#private", "https://gateway.invalid:bad/v1",
                                           "https://gateway.invalid:99999/v1", "https://gateway.invalid/\nprivate"],
                  "MIKASA_MODEL_API_KEY": ["", "private\nkey"],
                  "MIKASA_MODEL_API_MODE": ["private"], "MIKASA_MODEL": ["private\nmodel"]}
        for field, cases in values.items():
            for value in cases:
                with self.subTest(field=field, value=value), patch.dict(os.environ, {**self.env, field: value}, clear=True), \
                        patch("mikasa.native.prepare_profile") as run:
                    with self.assertRaises(MikasaError) as caught:
                        validate_environment(model_environment(self.config.data["worker"]), required=True)
                    run.assert_not_called()
                    self.assertNotIn("private", str(caught.exception))

    def test_environment_mapping_requires_explicit_names_and_never_falls_back(self):
        mapping = {key: 'VM_' + key for key in self.env}
        settings = {'model_source': {'type': 'environment', 'env': mapping},
                    'env_allowlist': list(mapping.values())}
        env = {mapping[key]: value for key, value in self.env.items()}
        with patch.dict(os.environ, {**self.env, **env}, clear=True):
            self.assertEqual(model_environment(settings), self.env)
            self.assertEqual(model_environment(settings, 'model-b')['MIKASA_MODEL'], 'model-b')
            for field, name in mapping.items():
                with self.subTest(field=field), patch.dict(os.environ, {**self.env, **env}, clear=True):
                    os.environ.pop(name)
                    with self.assertRaises(MikasaError):
                        model_environment(settings)
                    self.assertEqual(model_diagnostics(settings)['configuration'], 'invalid')
            with self.assertRaises(MikasaError):
                model_environment({**settings, 'env_allowlist': []})
        for source in ({'type': 'codex', 'env': mapping}, {'type': 'environment', 'env': []},
                       {'type': 'environment', 'env': {'TOKEN': 'VM_TOKEN'}},
                       {'type': 'environment', 'env': {'MIKASA_MODEL_API_KEY': 'private-key'}},
                       {'type': 'environment', 'env': {'MIKASA_MODEL_API_KEY': 42}}):
            with self.subTest(source=source), self.assertRaises(MikasaError):
                validate_source(source)

    def test_codex_bad_shapes_are_safe_and_environment_key_has_precedence(self):
        cfg = self.path / "codex.toml"
        auth = self.path / "auth.json"
        selection = {"model_source": {"type": "codex", "config_path": str(cfg), "auth_path": str(auth)}}
        cfg.write_text('model="model-a"\nmodel_provider="test"\n[model_providers.test]\nbase_url="https://gateway.invalid/v1"\nenv_key="TEST_MODEL_KEY"\n')
        for content in ('[]', '{"OPENAI_API_KEY": ["private"]}', '{"OPENAI_API_KEY": 42}'):
            auth.write_text(content)
            with patch.dict(os.environ, {}, clear=True):
                report = model_diagnostics(selection)
            self.assertEqual(report["configuration"], "invalid")
            self.assertNotIn("private", json.dumps(report))
        with patch.dict(os.environ, {"TEST_MODEL_KEY": "selected-key"}, clear=True):
            self.assertEqual(model_environment(selection)["MIKASA_MODEL_API_KEY"], "selected-key")

    def test_doctor_probe_is_explicit_and_does_not_create_chats(self):
        self.config.data["worker"].update(self.settings)
        with patch.dict(os.environ, self.env), patch("mikasa.cli.run_model_probe") as call:
            report = doctor(self.config)
            call.assert_not_called()
            self.assertEqual(report["model"]["connection"], "not_checked")
        # The actual fixture worker speaks our protocol but provides no model identity.
        with patch.dict(os.environ, self.env), patch("mikasa.cli.run_model_probe", return_value={}):
            report = doctor(self.config, probe_model=True)
        self.assertEqual(report["model"]["connection"], "passed")
        self.assertEqual(report["model"]["model_match"], "unreported")
        self.assertEqual(report["model"]["provider_group"], "unverified")
        self.assertFalse((self.config.runtime / 'mikasa.sqlite3').exists())

    def test_probe_failure_exit_and_missing_config(self):
        self.data["worker"].update(self.settings)
        self.write_config()
        with patch.dict(os.environ, self.env), patch("mikasa.cli.run_model_probe", side_effect=MikasaError("原生运行失败")), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--config", str(self.config_path), "doctor", "--probe-model"]), 1)
        self.assertEqual(json.loads(output.getvalue())["model"]["connection"], "failed")
        with patch.dict(os.environ, {}, clear=True), patch("mikasa.cli.run_model_probe") as call:
            report = doctor(self.config, probe_model=True)
        call.assert_not_called()
        self.assertEqual(report["model"]["configuration"], "invalid")
