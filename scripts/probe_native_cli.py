#!/usr/bin/env python3
"""Exercise the pinned Hermes CLI dispatcher against local provider catalogs; no model inference."""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.native import HERMES_REVISION, prepare_profile


def main():
    class Catalog(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'data': [{'id': 'gpt-6-astra'}, {'id': 'gpt-fixture-default'}, {'id': 'claude-opus-4-6'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Catalog)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='mkcli-', dir='/tmp') as directory:
            root = Path(__file__).resolve().parents[1]
            data = json.loads((root / 'config/examples/mikasa.json').read_text())
            data['runtime'] = directory
            endpoint = f'http://127.0.0.1:{server.server_port}'
            claude = Path(directory) / 'claude.json'
            claude.write_text(json.dumps({'env': {'ANTHROPIC_AUTH_TOKEN': 'claude-fixture',
                                                 'ANTHROPIC_BASE_URL': endpoint, 'ANTHROPIC_MODEL': 'claude-opus-4-6'}}))
            data['worker']['model_routes'] = [
                {'models': ['gpt-6-astra'], 'model_source': {'type': 'environment'}},
                {'models': ['claude-opus-4-6'], 'model_source': {'type': 'claude', 'config_path': str(claude)}},
            ]
            data['worker']['env_allowlist'] = ['MIKASA_MODEL', 'MIKASA_MODEL_BASE_URL', 'MIKASA_MODEL_API_KEY', 'MIKASA_MODEL_API_MODE']
            from unittest.mock import patch
            with patch.dict(os.environ, {'MIKASA_MODEL': 'gpt-fixture-default', 'MIKASA_MODEL_BASE_URL': endpoint + '/v1',
                                         'MIKASA_MODEL_API_KEY': 'synthetic-gpt-key', 'MIKASA_MODEL_API_MODE': 'codex_responses'}):
                config = Config(root, data)
                home, source, python, credentials = prepare_profile(config, config.owner)
                env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if k in os.environ}
                env.update(credentials, HERMES_HOME=str(home), PYTHONPATH=str(source), MIKASA_HERMES_SOURCE=str(source), HERMES_ENABLE_PROJECT_PLUGINS='0')
                code = '''import json
from pathlib import Path
from hermes_constants import get_hermes_home
from hermes_cli.plugins import discover_plugins
discover_plugins()
from cli import HermesCLI
c=HermesCLI(toolsets=['memory','skills'],compact=True)
checks={}
checks['native_version_command']=c.process_command('/version')
c.process_command('/model claude-opus-4-6 --session')
checks['native_claude_route']=c.model=='claude-opus-4-6' and c.api_mode=='anthropic_messages' and c.api_key=='claude-fixture'
history=[{'role':'user','content':'local history marker'},{'role':'assistant','content':'noted'}]
c.conversation_history=history.copy()
c.process_command('/model gpt-6-astra --global')
checks['native_gpt_route']=c.model=='gpt-6-astra' and c.api_mode=='codex_responses' and c.api_key=='synthetic-gpt-key'
checks['native_switch_preserves_history']=c.conversation_history==history
before=(c.model,c.provider,c.api_mode,c.api_key)
c.process_command('/model gpt-6-astra --once --global')
checks['native_invalid_switch_preserves_route']=before==(c.model,c.provider,c.api_mode,c.api_key)
sid=c.session_id
db=c._session_db
if not db.get_session(sid): db.create_session(sid,source='cli',model=c.model)
db.append_messages_batch(sid,[dict(m) for m in history])
c.conversation_history=[]
c.process_command('/model claude-opus-4-6 --session')
c.process_command('/new --yes')
checks['native_new_rotates_session']=c.session_id!=sid and not c.conversation_history
# Pinned upstream omits user_providers on its best-effort /new model reset.
# Record that limitation explicitly, rather than asserting a reset that did not happen.
checks['native_new_custom_provider_fallback_observed']=c.model=='claude-opus-4-6' and c.api_mode=='anthropic_messages'
c.process_command('/resume '+sid)
checks['native_resume_restores_history']=c.session_id==sid and [{k:m[k] for k in ('role','content')} for m in c.conversation_history]==history
from hermes_cli.config import load_config
from agent.skill_commands import build_auto_load_prompt
prompt,loaded,missing=build_auto_load_prompt(home_override=get_hermes_home())
checks['persona_active']='mikasa-persona' in loaded and not missing
checks['global_selection_saved']=load_config()['model']['default']=='gpt-6-astra'
print('MIKASA_PROBE='+json.dumps(checks))
'''
                result = subprocess.run([str(python), '-c', code], cwd=home / 'workspace', env=env,
                                        capture_output=True, text=True, timeout=90)
                if result.returncode:
                    # This probe only uses synthetic credentials, never real local CCH configuration.
                    raise RuntimeError(result.stderr[-2200:])
                checks = json.loads(next(line.removeprefix('MIKASA_PROBE=') for line in result.stdout.splitlines() if line.startswith('MIKASA_PROBE=')))
                if not all(checks.values()):
                    print(result.stdout[-4500:], file=sys.stderr)
                # Hermes writes YAML; refresh must parse it in the SDK environment and retain preferences.
                before = subprocess.check_output([str(python), '-c', "import yaml,json,os; from pathlib import Path; print(json.dumps(yaml.safe_load((Path(os.environ['HERMES_HOME'])/'config.yaml').read_text())['model']))"], env=env, text=True)
                prepare_profile(config, config.owner)
                checks['native_yaml_selection_survives_refresh'] = json.loads(before) == json.loads((home / 'config.yaml').read_text())['model']
                bootstrap = subprocess.run([str(python), str(root / 'workers/hermes/native_cli.py')],
                                           input='', cwd=home / 'workspace', env=env,
                                           capture_output=True, text=True, timeout=45)
                checks['native_entrypoint_starts_and_exits_on_eof'] = bootstrap.returncode == 0
                if bootstrap.returncode:
                    print(bootstrap.stderr[-2200:], file=sys.stderr)
                checks['no_model_keys_in_profile'] = not any(key.encode() in p.read_bytes() for key in credentials.values() for p in home.rglob('*') if p.is_file() and not p.is_symlink())
                print(json.dumps({'hermes_revision': HERMES_REVISION, 'checks': checks,
                                  'limitations': ['Pinned Hermes /new retains the current custom CCH provider; automatic default reset is not guaranteed.'],
                                  'passed': all(checks.values())}, indent=2))
                return 0 if all(checks.values()) else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


if __name__ == '__main__':
    raise SystemExit(main())
