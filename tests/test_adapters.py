import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

from mikasa.errors import MikasaError
from mikasa.github import GitHub
from mikasa.process import clean_env, run
from mikasa.skills import load_skills
from tests.support import BaseTest, REPO, ROOT, SHA


class AdapterTests(BaseTest):
    def test_github_pagination_and_ci_status(self):
        github = GitHub(self.config)
        def request(method, path, body=None):
            if "check-runs" in path:
                return {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "success"}]}
            return [{"context": "mikasa/approval", "state": "failure"},
                    {"context": "build", "state": "success"}, {"context": "build", "state": "failure"}]
        with patch.object(github, "request", side_effect=request):
            result = github.checks(REPO, SHA)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["statuses"]), 1)
        with patch.object(github, "request", return_value=list(range(100))) as call:
            with self.assertRaisesRegex(MikasaError, "2000"):
                github.paginate("/example")
            self.assertEqual(call.call_count, 20)

    def test_empty_ci_never_passes(self):
        github = GitHub(self.config)
        with patch.object(github, "paginate", return_value=[]):
            self.assertFalse(github.checks(REPO, SHA)["passed"])

    def test_gate_publication_binds_current_head(self):
        github = GitHub(self.config)
        verdict = {"allowed": True, "head": SHA}
        with patch.object(github, "verify_publisher"), patch.object(github, "gate", return_value=verdict), \
                patch.object(github, "pr", return_value={"head": {"sha": SHA}}), patch.object(github, "request") as request:
            github.publish_gate(REPO, 1, self.service.store)
            self.assertEqual(request.call_args.args[1], f"/repos/{REPO}/statuses/{SHA}")
            self.assertEqual(request.call_args.args[2]["context"], "mikasa/approval")
        with patch.object(github, "verify_publisher"), patch.object(github, "gate", return_value=verdict), \
                patch.object(github, "pr", return_value={"head": {"sha": "b" * 40}}), patch.object(github, "request") as request:
            with self.assertRaises(MikasaError):
                github.publish_gate(REPO, 1, self.service.store)
            request.assert_not_called()

    def test_http_request_never_redirects_credentials(self):
        github = GitHub(self.config)
        seen = []
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, limit):
                return b'{"login":"Mikasa-0910"}'
        def open_request(req, timeout):
            seen.append(req)
            return Response()
        with patch.dict(os.environ, {"MIKASA_GITHUB_TOKEN": "fixture"}), patch.object(github.opener, "open", side_effect=open_request):
            self.assertEqual(github.request("GET", "/user")["login"], self.config.bot)
        self.assertEqual(seen[0].full_url, "https://api.github.com/user")
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer fixture")
        from mikasa.github import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid"))

    def test_bridge_protocol_and_tool_isolation(self):
        # A signature-compatible SDK fixture verifies our adapter, not the real model.
        package = self.path / "hermes_cli"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "plugins.py").write_text('''
hooks = {}
class PluginManifest:
    def __init__(self, name): pass
class PluginContext:
    def __init__(self, manifest, manager): pass
    def register_hook(self, name, callback): hooks[name] = callback
def get_plugin_manager(): return None
''')
        (self.path / "run_agent.py").write_text('''
import json
import sys
class AIAgent:
    def __init__(self, **kwargs):
        assert kwargs['enabled_toolsets'] == []
        assert kwargs['skip_context_files'] and kwargs['skip_memory'] and kwargs['skip_background_review']
        assert kwargs['api_key'] == 'fixture-key'
        assert kwargs['api_mode'] == 'codex_responses'
        self.tools = []
        print('SDK log must not pollute stdout')
        print('fixture-key must not escape stderr', file=sys.stderr)
    def run_conversation(self, user_message, system_message):
        from hermes_cli.plugins import hooks
        hooks['post_api_request'](response_model='fixture-reported')
        assert system_message.startswith('canonical-rules')
        assert 'rules' not in json.loads(user_message)
        assert 'skills' not in json.loads(user_message)
        assert 'host instruction' in system_message
        assert '<project-skill name="mikasa-persona">' in system_message
        assert '<project-skill name="mikasa-implement">' in system_message
        assert 'Use the public behavior' in system_message
        return {'final_response': json.dumps({'summary': 'ok', 'changes': [{'path': 'app.py', 'content': 'VALUE = 2\\n'}]})}
''')
        env = clean_env({"PYTHONPATH": str(self.path), "HERMES_HOME": str(self.path / "hermes"),
                         "MIKASA_MODEL": "fixture", "MIKASA_MODEL_BASE_URL": "http://localhost:1234/v1",
                         "MIKASA_MODEL_API_KEY": "fixture-key", "MIKASA_MODEL_API_MODE": "codex_responses"})
        skills = load_skills(ROOT, "implement")
        output = run([sys.executable, str(ROOT / "workers/hermes/bridge.py")], cwd=self.path, env=env,
                     stdin=json.dumps({"version": 1, "rules": "canonical-rules", "task": {},
                                       "skills": skills, "instruction": "host instruction"}))
        self.assertEqual(output["code"], 0)
        envelope = json.loads(output["stdout"])
        self.assertEqual(envelope["result"]["summary"], "ok")
        self.assertEqual(envelope["runtime"]["tool_count"], 0)
        self.assertEqual(envelope["runtime"]["api_mode"], "codex_responses")
        self.assertEqual(envelope["runtime"]["reported_model"], "fixture-reported")
        self.assertEqual(envelope["runtime"]["skills"], [{k: s[k] for k in ("name", "sha256", "source")} for s in skills])
        self.assertEqual(envelope["result"]["changes"][0]["content"], "VALUE = 2\n")
        self.assertEqual(output["stderr"], "")

    def test_bridge_registered_tools_reach_host(self):
        from mikasa.agent_tools import ToolSession
        from mikasa.workspace import Workspace
        self.test_bridge_protocol_and_tool_isolation()
        plugin = self.path / "hermes_cli/plugins.py"
        plugin.write_text(plugin.read_text() + "\nregistered = {}\ndef register(self, name, toolset, schema, handler):\n    registered[name] = (schema, handler)\n    return True\nPluginContext.register_tool = register\n")
        (self.path / "model_tools.py").write_text("def get_tool_definitions(**kwargs):\n    from hermes_cli.plugins import registered\n    return [{'function': s} for s, h in registered.values()]\n")
        (self.path / "run_agent.py").write_text('''import json
from hermes_cli.plugins import registered
class AIAgent:
    def __init__(self, **kwargs):
        assert kwargs['enabled_toolsets'] == ['mikasa_workspace']
        self.tools = [{'function': s} for s, h in registered.values()]
    def run_conversation(self, **kwargs):
        result = json.loads(registered['mikasa_read_file'][1]({'path': 'app.py'}))
        assert 'VALUE = 1' in result['content']
        return {'final_response': json.dumps({'summary': 'read', 'tasks': [{'title':'change','acceptance':'value 2','depends_on':[]}]})}
''')
        workspace = Workspace(self.config, self.submit('plan'), 'adapter').prepare()
        with ToolSession(workspace, 'plan', lambda: False) as session:
            env = clean_env({"PYTHONPATH": str(self.path), "HERMES_HOME": str(self.path / "hermes"),
                             "MIKASA_MODEL": "fixture", "MIKASA_MODEL_BASE_URL": "http://localhost:1234/v1",
                             "MIKASA_MODEL_API_KEY": "fixture-key", "MIKASA_TOOL_FD": str(session.child.fileno())})
            result = run([sys.executable, str(ROOT / "workers/hermes/bridge.py")], cwd=self.path, env=env,
                         pass_fds=(session.child.fileno(),), stdin=json.dumps({"version":1, "rules":"rules", "tools":session.schemas}))
        self.assertEqual(result['code'], 0, result['stderr'])
        self.assertTrue(session.events[0]['ok'])
        envelope = json.loads(result['stdout'])
        self.assertEqual(len(envelope['runtime']['granted_tools']), 3)
        self.assertEqual(envelope['runtime']['tool_count'], 3)

    def test_bridge_failure_hook_and_recovery_discard_private_details(self):
        from mikasa.worker import Worker
        from mikasa.model_errors import ModelFailure
        self.test_bridge_protocol_and_tool_isolation()
        settings = self.config.data["worker"]
        settings.update({"command": [sys.executable, str(ROOT / "workers/hermes/bridge.py")],
                         "hermes_source": str(self.path), "home": str(self.path / "hermes"),
                         "env_allowlist": ["MIKASA_MODEL", "MIKASA_MODEL_BASE_URL", "MIKASA_MODEL_API_KEY"]})
        env = {"MIKASA_MODEL": "fixture", "MIKASA_MODEL_BASE_URL": "https://example.invalid/v1", "MIKASA_MODEL_API_KEY": "fixture-key"}
        for status, reason, expected in [(401, "auth", "auth"), (403, "auth", "access_denied"),
                                         (403, "upstream_blocked", "upstream_blocked"), (429, "rate_limit", "rate_limit"),
                                         (503, "overloaded", "unavailable"), (None, "timeout", "timeout")]:
            source = f'''import json
class AIAgent:
    def __init__(self, **kwargs): self.tools = []
    def run_conversation(self, **kwargs):
        from hermes_cli.plugins import hooks
        hooks['api_request_error'](status_code={status!r}, reason={reason!r}, error={{'message':'fixture-key'}}, request={{'Authorization':'fixture-key'}})
        return {{'failed':True, 'error':'fixture-key'}}
'''
            (self.path / "run_agent.py").write_text(source)
            with patch.dict(os.environ, env), self.assertRaises(ModelFailure) as caught:
                Worker(self.config).execute({"payload": {"kind": "chat"}}, {}, lambda: False)
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn("fixture-key", str(caught.exception))
        # Recovery clears the previous API failure; invalid output then has its own cause.
        (self.path / "run_agent.py").write_text(source.replace("return {'failed':True, 'error':'fixture-key'}",
            "hooks['post_api_request'](response_model='fixture')\n        return {'final_response':'not json fixture-key'}"))
        with patch.dict(os.environ, env), self.assertRaises(ModelFailure) as caught:
            Worker(self.config).execute({"payload": {"kind": "chat"}}, {}, lambda: False)
        self.assertEqual(caught.exception.code, "invalid_response")

    def test_docker_check_mounts_git_readonly_and_cleans_up(self):
        from mikasa.process import check_command
        with patch("mikasa.process.run", return_value={"code": 0, "stdout": "", "stderr": ""}) as proc:
            check_command(["pytest"], {"check_image": "fixture:1"}, self.repo, 5, lambda: False)
        argv = proc.call_args_list[0].args[0]
        self.assertIn("--network=none", argv)
        self.assertIn(f"type=bind,source={self.repo}/.git,target=/workspace/.git,readonly", argv)
        self.assertEqual(proc.call_args_list[1].args[0][:3], ["docker", "rm", "-f"])

    def test_cli_local_flow_and_backup(self):
        from mikasa.cli import main
        with redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(main(["--config", str(self.config_path), "submit", "audit", REPO, "Audit", "--acceptance", "report"]), 0)
        task = json.loads(captured.getvalue())
        self.assertEqual(task["state"], "queued")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--config", str(self.config_path), "backup", str(self.path / "backup.sqlite3")]), 0)
        self.assertEqual((self.path / "backup.sqlite3").stat().st_mode & 0o777, 0o600)
