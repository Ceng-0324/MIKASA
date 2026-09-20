import json
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from mikasa.errors import MikasaError
from mikasa.worker import Worker
from tests.support import BaseTest, command_reply
from workers.hermes.command_adapter import dispatch


class HermesCommandTests(BaseTest):
    def test_adapter_delegates_registry_and_model_parser(self):
        registry = ModuleType("hermes_cli.commands")
        registry.resolve_command = Mock(return_value=SimpleNamespace(name="model"))
        parser = ModuleType("hermes_cli.model_switch")
        parsed = SimpleNamespace(target="vendor/model:variant", errors=(), is_global=False,
                                 is_once=False, force_refresh=False, explicit_provider="", reasoning_effort="")
        parser.parse_model_switch_args = Mock(return_value=parsed)
        with patch.dict(sys.modules, {"hermes_cli.commands": registry, "hermes_cli.model_switch": parser}):
            result = dispatch("/MODEL vendor/model:variant —session")
            registry.resolve_command.assert_called_once_with("/MODEL")
            parser.parse_model_switch_args.assert_called_once_with("vendor/model:variant —session")
            self.assertEqual((result["kind"], result["target"]), ("switch", "vendor/model:variant"))
            for field, value in (("errors", ("conflict",)), ("is_global", True), ("is_once", True),
                                 ("force_refresh", True), ("explicit_provider", "foreign"), ("reasoning_effort", "high")):
                old = getattr(parsed, field)
                setattr(parsed, field, value)
                self.assertEqual(dispatch("/model input")["kind"], "help")
                setattr(parsed, field, old)

    def test_command_rpc_does_not_read_or_inherit_credentials(self):
        self.config.data["worker"]["env_allowlist"] = ["MIKASA_MODEL_API_KEY", "GH_TOKEN"]
        self.config.data["worker"]["model_source"] = {"type": "codex", "config_path": "/nonexistent/private"}
        envelope = {"version": 1, "result": command_reply("/model")}
        with patch.dict(os.environ, {"MIKASA_MODEL_API_KEY": "private", "GH_TOKEN": "private"}), \
                patch("mikasa.worker.model_environment", side_effect=AssertionError("must not read credentials")), \
                patch("mikasa.worker.run", return_value={"code": 0, "stdout": json.dumps(envelope)}) as run:
            self.assertEqual(Worker(self.config).command("/model", lambda: False)["kind"], "status")
        env = run.call_args.kwargs["env"]
        self.assertNotIn("MIKASA_MODEL_API_KEY", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertEqual(json.loads(run.call_args.kwargs["stdin"]), {"version": 1, "operation": "command", "text": "/model"})

    def test_bad_command_rpc_fails_closed_without_sdk_details(self):
        for code, output in [(1, "private SDK diagnostic"), (0, '{"version":1,"result":{}}'),
                             (0, json.dumps({"version": 1, "result": {**command_reply("/model model-b"), "target": None}}))]:
            with patch("mikasa.worker.run", return_value={"code": code, "stdout": output}), \
                    self.assertRaisesRegex(MikasaError, "命令未执行"):
                Worker(self.config).command("/model", lambda: False)
