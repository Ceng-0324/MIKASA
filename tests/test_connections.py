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
from mikasa.connections import (diagnostics, feishu_environment, messaging_gateway, probe_feishu,
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
        with patch.dict(os.environ, {"MIKASA_FEISHU_APP_ID": "cli_fixture", "MIKASA_FEISHU_APP_SECRET": "fixture-secret"}):
            self.assertEqual(feishu_environment(self.config)["FEISHU_ALLOW_ALL_USERS"], "true")
            result = diagnostics(self.config, "feishu")
        self.assertEqual(result["configuration"], "ready")
        self.assertFalse(result["owner_bound"])
        self.assertEqual(result["access"], {"users": "all", "groups": "open", "bots": "all", "require_mention": False})

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
        with patch.dict(os.environ, {}, clear=True), patch("mikasa.native.NativeGateways") as service, \
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
            env, settings = messaging_gateway(self.config, ('feishu',))
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
group = N(chat_type='group', chat_id='oc_fixture', mentions=[], content='ordinary unmentioned text')
adapter._bot_open_id = 'ou_mikasa_bot'
from gateway.authz_mixin import GatewayAuthorizationMixin
from gateway.session import build_session_key
auth = GatewayAuthorizationMixin()
auth.adapters = {Platform.FEISHU: adapter}
auth.config = config
sources = []
for sender in (owner, stranger, bot):
    for message in (dm, group):
        assert adapter._admit(sender, message) is None, (sender, message)
        resolved = asyncio.run(adapter._resolve_sender_profile(sender.sender_id))
        source = adapter.build_source(chat_id=message.chat_id,
            chat_type='dm' if message is dm else 'group', **resolved)
        source.is_bot = sender is bot
        assert auth._is_user_authorized(source), (sender, message)
        sources.append(source)
assert build_session_key(sources[0]) != build_session_key(sources[1])
assert build_session_key(sources[1]) != build_session_key(sources[3])
# Native identity/loop defenses remain active even when channel admission is open.
self_sender = N(sender_type='bot', sender_id=N(open_id='ou_mikasa_bot', user_id=None, union_id=None))
assert adapter._admit(self_sender, group) == 'self_echo'
for _ in range(100):
    if not auth._admit_bot_message(sources[-1]):
        break
else:
    raise AssertionError('native bot loop guard must stop repeated bot traffic')
assert not auth._is_user_authorized(sources[-1])
assert auth._is_user_authorized(sources[3]), 'bot cooldown must not block humans'
for tenant_id in (None, 'owner_tenant_id'):
    owner.sender_id.user_id = tenant_id
    resolved = asyncio.run(adapter._resolve_sender_profile(owner.sender_id))
    source = adapter.build_source(chat_id='oc_fixture', chat_type='dm', **resolved)
    assert auth._is_user_authorized(source)
# Validate the native startup opt-in, not just the adapter's local policy.
from gateway.run_startup import GatewayStartupMixin
startup = GatewayStartupMixin()
startup.config = config
assert not startup._start_check_access_policy()
print('pinned Feishu SDK admission and Gateway configuration: passed')
'''
        reply = subprocess.run([str(python), "-c", code], cwd=self.path, env=env,
                               input=json.dumps(settings), capture_output=True, text=True, timeout=30)
        self.assertEqual(reply.returncode, 0, reply.stderr)

    def test_native_sethome_survives_profile_refresh_restart_and_env_free_restore(self):
        from mikasa.native import prepare_profile
        self.native_python("dotenv", "openai", "anthropic", "aiohttp")
        model_env = {"MIKASA_MODEL": "fixture-model", "MIKASA_MODEL_BASE_URL": "https://cch.invalid/v1",
                     "MIKASA_MODEL_API_KEY": "fixture-model-secret", "MIKASA_MODEL_API_MODE": "codex_responses"}
        with patch.dict(os.environ, model_env):
            home, source, python, credentials = prepare_profile(self.config, self.config.owner)
        explicit = home / 'gateway-messaging.json'
        explicit.write_text(json.dumps({'platforms': {
            name: {'enabled': True, 'gateway_restart_notification': False, 'extra': {'fixture': True}}
            for name in ('feishu', 'weixin')}}))
        env = {"PATH": os.environ.get("PATH", ""), "HERMES_HOME": str(home),
               "MIKASA_HERMES_SOURCE": str(source), "HERMES_ENABLE_PROJECT_PLUGINS": "0", **credentials}
        code = '''
import asyncio, json, os, sys
from pathlib import Path
from types import SimpleNamespace as N
sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
sys.path.insert(0, sys.argv[1])
from gateway.run import GatewayRunner
from gateway.config import GatewayConfig, Platform
from workers.hermes.native_gateway import messaging_config
home = Path(os.environ['HERMES_HOME'])
if sys.argv[2] == 'save':
    runner = N(config=GatewayConfig())
    for name in ('feishu', 'weixin'):
        source = N(platform=Platform(name), chat_id=name+'-chat', chat_name='Home',
                   user_id=name+'-user', scope_id=name+'-scope', thread_id=None,
                   chat_type='dm', delivered_via_upstream_relay=False)
        asyncio.run(GatewayRunner._handle_set_home_command(runner, N(source=source)))
    assert (home / '.env').exists()
config = messaging_config(home / 'gateway-messaging.json')
assert set(config.platforms) == {Platform.FEISHU, Platform.WEIXIN}
assert config.max_concurrent_sessions is None
assert config.streaming.enabled
from gateway.session import SessionSource, build_session_key
from gateway.platforms.event import MessageEvent
assert GatewayRunner._load_busy_input_mode() == 'queue'
from agent.i18n import get_language, t
assert get_language() == 'zh'
assert '会话' in t('gateway.model.session_only_hint')
from unittest.mock import AsyncMock, patch
result = N(new_model='fixture-model', target_provider='custom', provider_label='CCH',
           base_url='', api_key='', model_info=None, api_mode='codex_responses', warning_message=None)
ctx = N(persist_global=False, current_base_url='', current_api_key='', custom_provs=[])
with patch('hermes_cli.model_switch.resolve_display_context_length_async', new=AsyncMock(return_value=None)):
    reply = asyncio.run(GatewayRunner._model_switch_confirmation(N(), result, ctx, one_turn=False, picker=False))
    assert t('gateway.model.session_only_hint') in reply
    once = asyncio.run(GatewayRunner._model_switch_confirmation(N(), result, ctx, one_turn=True, picker=False))
    assert 'next turn only' in once
    ctx.persist_global = True
    saved = asyncio.run(GatewayRunner._model_switch_confirmation(N(), result, ctx, one_turn=False, picker=False))
    assert t('gateway.model.saved_global') in saved
    failed = asyncio.run(GatewayRunner._model_switch_confirmation(N(), result, ctx, one_turn=False, picker=False, global_error='fixture write failed'))
    assert t('gateway.model.session_only_hint') in failed and t('gateway.model.saved_global') not in failed
runner = object.__new__(GatewayRunner)
runner.config = config
runner._session_state('user-a').turn.agent = object()
assert runner._active_session_limit_message('user-b') is None
config.max_concurrent_sessions = 1
assert '(1/1)' in runner._active_session_limit_message('user-b')
config.max_concurrent_sessions = None
adapter = N(_pending_messages={})
received = []
for user in ('a', 'b'):
    source = SessionSource(platform=Platform.FEISHU, chat_id='group', chat_type='group', user_id=user)
    key = build_session_key(source, group_sessions_per_user=config.group_sessions_per_user)
    received.append(key)
    runner._enqueue_fifo(key, MessageEvent(text=user, source=source), adapter)
assert received[0] == received[1], 'group participants must share context'
key = received[0]
assert runner._queue_depth(key, adapter=adapter) == 2
first = adapter._pending_messages.pop(key)
assert runner._promote_queued_event(key, adapter, first).text == 'a'
assert adapter._pending_messages.pop(key).text == 'b'
assert runner._queue_depth(key, adapter=adapter) == 0
for name in ('feishu', 'weixin'):
    settings = config.platforms[Platform(name)]
    assert settings.home_channel.chat_id == name+'-chat'
    assert settings.home_channel.user_id == name+'-user'
    assert settings.home_channel.scope_id == name+'-scope'
    assert settings.extra == {'fixture': True}
    assert not settings.gateway_restart_notification
assert 'fixture-model-secret' in os.environ.values()
'''
        def check(mode):
            result = subprocess.run([str(python), '-c', code, str(ROOT), mode],
                                    cwd=home / 'workspace', env=env, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
        check('save')
        original = (home / '.env').read_bytes()
        with patch.dict(os.environ, model_env):
            prepare_profile(self.config, self.config.owner)
        self.assertEqual((home / '.env').read_bytes(), original)
        check('restart')
        (home / '.env').unlink()  # Backups keep canonical config.yaml, never credential files.
        check('restored')

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
        # Full canonical rules are native skill content, not permanent chat sections.
        generated = (home / 'skills/mikasa-engineering/SKILL.md').read_text()
        code = '''
import os,sys,json
from pathlib import Path
sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
from hermes_cli.plugins import discover_plugins, render_system_prompt_sections, get_pre_tool_call_directive
from tools.skills_tool import skill_view
discover_plugins()
sections=''.join(s.content for s in render_system_prompt_sections({}))
home=Path(os.environ['HERMES_HOME'])
for name in ('engineering-contract.md', 'engineering-workflow.md'):
    assert (home/'policy'/name).read_text() not in sections
skill=json.loads(skill_view('mikasa-engineering'))
assert '工程工作流' in json.dumps(skill,ensure_ascii=False)
assert get_pre_tool_call_directive('session_search', {'query': 'past discussion'})[0] is None
for name in ('tool_search', 'tool_describe', 'tool_call'):
    assert get_pre_tool_call_directive(name, {})[0] is None
from model_tools import handle_function_call
from agent.tool_executor import _unwrap_tool_search_call
from types import SimpleNamespace
toolsets=['memory','skills','session_search']
described=json.loads(handle_function_call('tool_describe', {'names':['session_search']}, enabled_toolsets=toolsets))
assert 'session_search' in described.get('tools',{})
name,args,blocked=_unwrap_tool_search_call(SimpleNamespace(enabled_toolsets=toolsets), 'tool_call', {'name':'session_search','arguments':{'profile':'other','query':'private'}})
assert name == 'session_search' and blocked is None
assert get_pre_tool_call_directive(name, args)[0] is None
for args in ({'profile':'other'}, {'session_id':'other/id'}):
    assert get_pre_tool_call_directive('session_search', args)[0] is None
from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
from gateway.display_config import resolve_display_setting
cfg=load_config()
for platform in ('feishu','weixin'):
    enabled=sorted(_get_platform_tools(cfg,platform))
    tools={t['function']['name'] for t in get_tool_definitions(enabled_toolsets=enabled,quiet_mode=True,skip_tool_search_assembly=True)}
    assert {'terminal','read_file','write_file','process_manage','delegate_task','skill_manage'} <= tools, tools
    assert resolve_display_setting(cfg,platform,'tool_progress') == 'all'
    assert resolve_display_setting(cfg,platform,'interim_assistant_messages')
    assert resolve_display_setting(cfg,platform,'long_running_notifications')
assert cfg['agent']['gateway_notify_interval'] == 15
for name in ('terminal','write_file','delegate_task','skill_manage','web_search'):
    assert get_pre_tool_call_directive(name, {})[0] is None
# Exercise the actual pinned SessionDB, including deduplicated prompt storage,
# hidden/archived rows and more than the native default page of 20 sessions.
import importlib.util
from hermes_state import SessionDB
spec=importlib.util.spec_from_file_location('mikasa_plugin_test',home/'plugins/mikasa/__init__.py')
plugin=importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
policy=[s.content for s in render_system_prompt_sections({})]
soul=(home/'SOUL.md').read_text().strip()
fresh='mikasa.policy.0 '+soul+' '+''.join(policy)
db=SessionDB(home/'state.db')
for i in range(23):
    db.create_session('stale-'+str(i),source='feishu',system_prompt='mikasa.policy.0 old identity')
db.set_session_hidden('stale-0',True)
db.set_session_archived('stale-1',True)
db.create_session('current',source='weixin',system_prompt=fresh)
db.create_session('foreign',source='cli',system_prompt='unrelated prompt')
db.create_session('policy-old',source='feishu',system_prompt='mikasa.policy.0 '+soul)
db.append_message('stale-0','user','history must survive')
history=db.get_messages('stale-0')
db.close()
assert plugin.refresh_identity_prompts(home,policy) == 24
db=SessionDB(home/'state.db')
assert db.get_session('stale-0')['system_prompt'] is None
assert db.get_session('stale-22')['system_prompt'] is None
assert db.get_session('current')['system_prompt'] == fresh
assert db.get_session('foreign')['system_prompt'] == 'unrelated prompt'
assert db.get_messages('stale-0') == history
assert db.get_session('stale-0')['hidden']
assert db.get_session('stale-1')['archived']
db.close()
assert plugin.refresh_identity_prompts(home,policy) == 0
'''
        for name in ('engineering-contract.md', 'engineering-workflow.md'):
            self.assertIn((ROOT / name).read_text(), generated)
        reply = subprocess.run([str(python), '-c', code], cwd=home / 'workspace', env=env,
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(reply.returncode, 0, reply.stderr)
        # A broken explicit platform must exit before the native cron-only fallback.
        invalid = home / 'invalid-gateway.json'
        invalid.write_text(json.dumps({'platforms': {'feishu': {'enabled': True}}}))
        reply = subprocess.run([str(python), str(ROOT / 'workers/hermes/native_gateway.py'), '--config', str(invalid)],
                               cwd=home / 'workspace', env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(reply.returncode, 0)
        self.assertIn('Messaging platform prerequisites missing', reply.stderr)
        self.assertFalse((home / 'gateway.pid').exists())
