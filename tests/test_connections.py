import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mikasa.cli import main
from mikasa.config import Config
from mikasa.connections import (diagnostics, feishu_environment, feishu_gateway_config, probe_feishu,
                                login_weixin, validate_weixin_binding, weixin_binding)
from mikasa.errors import Forbidden, MikasaError
from mikasa.github import GitHub
from tests.support import ROOT


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="connections-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.data = json.loads((ROOT / "config/examples/mikasa.json").read_text())
        self.data.update(project_root=str(ROOT), runtime=str(self.path / "state"))
        self.data["feishu"] = {"domain": "feishu", "owner_open_id": "ou_owner"}
        self.config = Config(ROOT, self.data)

    def native_python(self, *modules):
        python = ROOT / "runtime/cache/hermes-venv/bin/python"
        if not python.is_file():
            self.skipTest("requires pinned Hermes SDK")
        check = subprocess.run([str(python), "-c",
            "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(n) for n in sys.argv[1:]) else 77)",
            *modules], capture_output=True, timeout=10)
        if check.returncode == 77:
            self.skipTest("requires full Hermes dependencies: " + ", ".join(modules))
        self.assertEqual(check.returncode, 0)
        return python

    def test_configuration_rejects_unbound_wildcard_or_inline_credentials(self):
        path = self.path / "config.json"
        for feishu in ({"owner_open_id": "*"}, {"owner_open_id": "ou_a,ou_b"},
                       {"domain": "https://untrusted.invalid"}, {"app_secret": "secret"},
                       {"app_id_env": "secret-value"}, {"owner_user_id": "*"}):
            with self.subTest(feishu=feishu):
                path.write_text(json.dumps({**self.data, "feishu": feishu}))
                with self.assertRaises(MikasaError):
                    Config.load(path)
        self.data["feishu"] = {}
        with self.assertRaisesRegex(MikasaError, "绑定负责人"):
            feishu_environment(self.config)

    def test_weixin_binding_fails_closed_and_diagnostics_do_not_expose_credentials(self):
        value = {"actor": self.config.owner, "account_id": "fixture@im.bot", "user_id": "owner@im.wechat",
                 "token": "private-fixture", "base_url": "https://ilinkai.weixin.qq.com"}
        self.assertEqual(diagnostics(self.config, "weixin")["configuration"], "incomplete")
        self.assertFalse(self.config.runtime.exists())
        for change in ({"user_id": ""}, {"user_id": "*"}, {"user_id": "a,b"}, {"actor": "stranger"},
                       {"account_id": "../secret"}, {"token": ""}, {"base_url": "https://weixin.qq.com.evil.invalid"},
                       {"base_url": "http://ilinkai.weixin.qq.com"}):
            with self.subTest(change=change), self.assertRaises(MikasaError):
                validate_weixin_binding({**value, **change}, self.config.owner)
        path = self.config.runtime / "credentials/weixin.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        self.assertEqual(weixin_binding(self.config), value)
        result = diagnostics(self.config, "weixin")
        self.assertEqual(result["configuration"], "ready")
        self.assertEqual(result["connection"], "not_checked")
        self.assertNotIn("private-fixture", json.dumps(result))
        self.assertNotIn("owner@im.wechat", json.dumps(result))
        with self.assertRaises(MikasaError):
            diagnostics(self.config, "weixin", probe=True)
        path.chmod(0o644)
        with self.assertRaises(MikasaError):
            weixin_binding(self.config)

    def test_weixin_login_is_model_independent_and_preserves_active_profile(self):
        with patch.dict(os.environ, {"GH_TOKEN": "unrelated", "MIKASA_MODEL_API_KEY": "unrelated"}), \
                patch("mikasa.connections.subprocess.run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(login_weixin(self.config), 0)
        self.assertNotIn("GH_TOKEN", run.call_args.kwargs["env"])
        self.assertNotIn("MIKASA_MODEL_API_KEY", run.call_args.kwargs["env"])
        self.assertFalse(Path(run.call_args.kwargs["env"]["HERMES_HOME"]).exists())
        self.assertFalse((self.config.runtime / "native").exists())

    def test_native_qr_worker_publishes_only_complete_binding_and_preserves_previous_on_failure(self):
        python = self.native_python("aiohttp", "cryptography")
        destination = self.path / "binding.json"
        code = '''
import os, sys, runpy
sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
from gateway.platforms import weixin
user_id = sys.argv[3]
async def login(home):
    return {'account_id': 'fixture@im.bot', 'token': 'private-fixture',
            'base_url': 'https://ilinkai.weixin.qq.com', 'user_id': user_id}
weixin.qr_login = login
sys.argv = [sys.argv[1], sys.argv[2], 'Ceng-0324']
runpy.run_path(sys.argv[0], run_name='__main__')
'''
        env = {"PATH": os.environ.get("PATH", ""), "HERMES_HOME": str(self.path),
               "MIKASA_HERMES_SOURCE": str(ROOT / "runtime/cache/hermes-source")}
        for user, status in (("owner@im.wechat", 0), ("", 1)):
            reply = subprocess.run([str(python), "-c", code, str(ROOT / "workers/hermes/weixin_login.py"),
                                    str(destination), user], cwd=self.path, env=env,
                                   capture_output=True, text=True, timeout=20)
            self.assertEqual(reply.returncode, status, reply.stderr)
            self.assertNotIn("private-fixture", reply.stdout + reply.stderr)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(destination.read_text())["user_id"], "owner@im.wechat")

    def test_default_diagnostics_never_start_services_or_use_network(self):
        path = self.path / "config.json"
        path.write_text(json.dumps(self.data))
        with patch.dict(os.environ, {}, clear=True), patch("mikasa.cli.Service") as service, \
                patch("mikasa.github.GitHub.request") as request, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--config", str(path), "connections", "github"]), 1)
        service.assert_not_called()
        request.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["connection"], "not_checked")
        self.assertFalse(self.config.runtime.exists())

    def test_github_probe_requires_bot_and_does_not_infer_write_access(self):
        self.data["repositories"] = {"Ceng-0324/Test": {"base": "feature/test"}}
        github = GitHub(self.config)
        replies = [{"login": "Mikasa-0910"}, {"full_name": "Ceng-0324/Test", "private": True,
                                                "permissions": {"push": True}}, {"name": "feature/test"}, [], []]
        with patch.object(github, "request", side_effect=replies) as request:
            result = github.probe()
        self.assertEqual(result["connection"], "passed")
        self.assertEqual(result["write_access"], "not_checked")
        self.assertTrue(result["repositories"][0]["account_push_role"])
        self.assertTrue(all(call.args[0] == "GET" for call in request.call_args_list))
        self.assertIn("feature%2Ftest", request.call_args_list[2].args[1])
        with patch.object(github, "request", return_value={"login": "Ceng-0324"}) as request:
            with self.assertRaises(Forbidden):
                github.probe()
        self.assertEqual(request.call_count, 1)

    def test_github_account_needs_no_repository_but_configured_branch_must_exist(self):
        github = GitHub(self.config)
        with patch.object(github, "request", return_value={"login": "Mikasa-0910"}) as request:
            result = github.probe()
        self.assertEqual(result["connection"], "passed")
        self.assertEqual(result["repository_access"], "not_checked")
        self.assertEqual(result["write_access"], "not_checked")
        request.assert_called_once_with("GET", "/user")
        path = self.path / "config.json"
        path.write_text(json.dumps(self.data))
        with patch.dict(os.environ, {"MIKASA_GITHUB_TOKEN": "fixture-token"}), \
                patch("mikasa.github.GitHub.request", return_value={"login": "Mikasa-0910"}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--config", str(path), "connections", "github", "--probe"]), 0)
        self.assertEqual(json.loads(output.getvalue())["configuration"], "ready")
        self.assertFalse(self.config.runtime.exists())
        self.data["repositories"] = {"Ceng-0324/Test": {"base": "main"}}
        with patch.object(github, "request", side_effect=[{"login": "Mikasa-0910"},
                {"full_name": "Ceng-0324/Test"}, MikasaError("GitHub HTTP 404")]):
            result = github.probe()
        self.assertEqual(result["connection"], "incomplete")
        self.assertEqual(result["repositories"][0]["read_access"], "failed")

    def test_feishu_probe_is_ephemeral_redacts_output_and_does_not_need_model(self):
        with patch.dict(os.environ, {"MIKASA_FEISHU_APP_ID": "cli_fixture", "MIKASA_FEISHU_APP_SECRET": "fixture-secret",
                                     "GH_TOKEN": "unrelated"}), \
                patch("mikasa.connections.subprocess.run", return_value=Mock(returncode=0, stdout='{"connection":"passed","bot_identity":"passed"}')) as run:
            result = diagnostics(self.config, "feishu", probe=True)
        self.assertEqual(result["connection"], "passed")
        self.assertEqual(result["messages"], "not_checked")
        self.assertNotIn("GH_TOKEN", run.call_args.kwargs["env"])
        self.assertNotIn("fixture-secret", repr(run.call_args.args))
        self.assertFalse(Path(run.call_args.kwargs["env"]["HERMES_HOME"]).exists())
        self.assertFalse(self.config.runtime.exists())
        with patch.dict(os.environ, {"MIKASA_FEISHU_APP_ID": "cli_fixture", "MIKASA_FEISHU_APP_SECRET": "fixture-secret"}), \
                patch("mikasa.connections.subprocess.run", side_effect=subprocess.TimeoutExpired("probe", 45, output="fixture-secret")):
            with self.assertRaises(MikasaError) as error:
                probe_feishu(self.config)
        self.assertNotIn("fixture-secret", str(error.exception))

    def test_pinned_feishu_sdk_admission_and_gateway_contract(self):
        python = self.native_python("lark_oapi")
        self.data["feishu"]["owner_user_id"] = "owner_tenant_id"
        with patch.dict(os.environ, {"MIKASA_FEISHU_APP_ID": "cli_fixture", "MIKASA_FEISHU_APP_SECRET": "fixture-secret"}):
            env = feishu_environment(self.config)
        env.update(HERMES_HOME=str(self.path), MIKASA_HERMES_SOURCE=str(ROOT / "runtime/cache/hermes-source"),
                   HERMES_ENABLE_PROJECT_PLUGINS="0", PATH=os.environ.get("PATH", ""))
        code = '''
import asyncio, json, os, sys
from types import SimpleNamespace as N
sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
from hermes_cli.plugins import discover_plugins
discover_plugins()
from gateway.config import GatewayConfig, Platform
from gateway.platform_registry import platform_registry
entry = platform_registry.get('feishu')
assert entry.check_fn(), 'full dependency snapshot must satisfy registry before SDK import'
config = GatewayConfig.from_dict(json.load(sys.stdin))
assert list(config.platforms) == [Platform.FEISHU]
assert config.unauthorized_dm_behavior == 'ignore'
adapter = platform_registry.create_adapter('feishu', config.platforms[Platform.FEISHU])
assert adapter is not None, 'native registry must accept dependency and config contracts'
assert sys.modules[type(adapter).__module__]._load_lark_oapi()
assert adapter._connection_mode == 'websocket'
assert not config.platforms[Platform.FEISHU].gateway_restart_notification
assert adapter._build_event_handler() is not None
owner = N(sender_type='user', sender_id=N(open_id='ou_owner', user_id=None, union_id='on_owner'))
stranger = N(sender_type='user', sender_id=N(open_id='ou_stranger', user_id=None, union_id=None))
bot = N(sender_type='bot', sender_id=N(open_id='ou_owner', user_id=None, union_id=None))
dm = N(chat_type='p2p', chat_id='oc_fixture')
assert adapter._admit(owner, dm) is None
assert adapter._admit(stranger, dm) == 'dm_policy_rejected'
assert adapter._admit(bot, dm) == 'bots_disabled'
assert adapter._admit(owner, N(chat_type='group', chat_id='oc_fixture')) == 'group_policy_rejected'
from gateway.authz_mixin import _principal_matches_allowlist
for tenant_id in (None, 'owner_tenant_id'):
    owner.sender_id.user_id = tenant_id
    resolved = asyncio.run(adapter._resolve_sender_profile(owner.sender_id))
    source = adapter.build_source(chat_id='oc_fixture', chat_type='dm', **resolved)
    assert _principal_matches_allowlist(source, source.user_id, set(os.environ['FEISHU_ALLOWED_USERS'].split(',')))
print('pinned Feishu SDK admission and Gateway configuration: passed')
'''
        reply = subprocess.run([str(python), "-c", code], cwd=self.path, env=env,
                               input=json.dumps(feishu_gateway_config('cli_fixture')), capture_output=True, text=True, timeout=30)
        self.assertEqual(reply.returncode, 0, reply.stderr)

    def test_pinned_gateway_entry_loads_identity_policy_and_persona_without_connecting(self):
        from mikasa.native import prepare_profile
        self.native_python("openai", "anthropic", "aiohttp")
        with patch.dict(os.environ, {"MIKASA_MODEL": "fixture-model", "MIKASA_MODEL_BASE_URL": "https://cch.invalid/v1",
                                     "MIKASA_MODEL_API_KEY": "fixture-model-secret", "MIKASA_MODEL_API_MODE": "codex_responses"}):
            home, source, python, credentials = prepare_profile(self.config, self.config.owner)
        env = {"PATH": os.environ.get("PATH", ""), "HERMES_HOME": str(home), "MIKASA_HERMES_SOURCE": str(source),
               "HERMES_ENABLE_PROJECT_PLUGINS": "0", **credentials}
        # --help exits before starting a Gateway, after the launcher's mandatory plugin/skill checks.
        reply = subprocess.run([str(python), str(ROOT / "workers/hermes/native_gateway.py"), "--help"],
                               cwd=home / "workspace", env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(reply.returncode, 0, reply.stderr)
        self.assertIn("Hermes Gateway", reply.stdout)
        loaded = json.loads((home / "policy-loaded.json").read_text())
        self.assertGreater(loaded["policy_chars"], 0)
        self.assertTrue(loaded["native_memory"])
        self.assertEqual((home / "SOUL.md").read_text(), (ROOT / "identity.md").read_text())
        # A broken explicit platform must exit before the native cron-only fallback.
        invalid = home / 'invalid-gateway.json'
        invalid.write_text(json.dumps({'platforms': {'feishu': {'enabled': True}}}))
        reply = subprocess.run([str(python), str(ROOT / 'workers/hermes/native_gateway.py'), '--config', str(invalid)],
                               cwd=home / 'workspace', env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(reply.returncode, 0)
        self.assertIn('Messaging platform prerequisites missing', reply.stderr)
        self.assertFalse((home / 'gateway.pid').exists())
