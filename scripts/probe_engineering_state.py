#!/usr/bin/env python3
"""Real pinned SDK/Docker with a local model fixture; no CCH or platform credentials."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.engineering import engineering_profile
from mikasa.model_errors import ModelFailure
from mikasa.native import HERMES_REVISION, prepare_profile
from mikasa.process import clean_env, git
from mikasa.sandbox import IMAGE
from mikasa.service import Service
from mikasa.skills import load_skills
from mikasa.worker import Worker
from mikasa.workspace import Workspace


def main():
    root = Path(__file__).resolve().parents[1]
    checks, requests, containers = {}, [], []
    turn, step = 0, 0
    scenario = 'continuity'

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal step
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path == '/api/show':
                self.send_error(404)
                return
            if 'messages' not in body:
                raise RuntimeError('Unexpected fixture request: ' + self.path + ' fields=' + str(list(body)))
            messages = body['messages']
            engineering = bool(body.get('tools')) and any(m.get('role') == 'user' and isinstance(m.get('content'), str)
                              and m['content'].startswith('按 output_contract 返回一个 JSON 对象') for m in messages)
            if engineering:
                requests.append(body)
            if not engineering:
                message, reason = {'role': 'assistant', 'content': 'Fixture metadata'}, 'stop'
            elif scenario != 'continuity':
                check_call = ('tool_call', {'calls': [{'name': 'mikasa_run_checks', 'arguments': {}}]})
                bad = ('write_file', {'path': '/workspace/calc.py', 'content': 'VALUE = 0\n'})
                good = ('write_file', {'path': '/workspace/calc.py', 'content': 'VALUE = 2\n'})
                actions = {'repair': [bad, check_call, good, check_call],
                           'unfinished': [bad, check_call], 'regressed': [good, check_call, bad]}[scenario]
                if step < len(actions):
                    name, arguments = actions[step]
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [
                        {'id': scenario + '-' + str(step), 'type': 'function',
                         'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
                    reason = 'tool_calls'
                else:
                    message = {'role': 'assistant', 'content': json.dumps({'summary': scenario, 'changes': []})}
                    reason = 'stop'
            elif turn == 0 and step < 2:
                name, arguments = ('read_file', {'path': '/workspace/calc.py'}) if step == 0 else (
                    'memory', {'action': 'add', 'target': 'memory', 'content': 'Engineering confirmed convention marker.'})
                message = {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'fixture-call-' + str(step), 'type': 'function',
                     'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
                reason = 'tool_calls'
            else:
                message = {'role': 'assistant', 'content': 'invalid result' if turn == 2 else json.dumps({
                    'summary': 'fixture completed ' + str(turn),
                    'tasks': [{'title': 'fixture task', 'acceptance': 'fixture acceptance', 'depends_on': []}]})}
                reason = 'stop'
            if engineering and scenario == 'continuity' and turn == 0 and step == 1:
                payload = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'user').split('\n', 1)[1])
                run_id = payload['native']['run_id']
                ids = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=hermes-task-id=' + run_id], text=True).split()
                containers.extend(ids)
                checks['bridge_run_id_matches_live_container'] = len(ids) == 1
                if ids:
                    info = json.loads(subprocess.check_output(['docker', 'inspect', ids[0]], text=True))[0]
                    mounted = [Path(m['Source']).resolve() for m in info['Mounts']]
                    checks['account_profile_not_mounted'] = all(
                        not (p.is_relative_to(account) or account.is_relative_to(p)) for p in mounted)
                    protected = [home / name for name in ('memories', 'state.db', 'config.yaml', 'SOUL.md')]
                    checks['engineering_private_state_not_mounted'] = all(
                        not (p.is_relative_to(secret.resolve()) or secret.resolve().is_relative_to(p))
                        for p in mounted for secret in protected)
                    checks['model_key_not_in_container'] = 'synthetic-engineering-key' not in json.dumps(info)
            if engineering:
                step += 1
            response = {'id': 'fixture-response', 'object': 'chat.completion', 'created': 1, 'model': 'fixture-model',
                        'choices': [{'index': 0, 'message': message, 'finish_reason': reason}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130}}
            if body.get('stream'):
                delta = dict(message)
                if 'tool_calls' in delta:
                    delta['tool_calls'] = [dict(c, index=i) for i, c in enumerate(delta['tool_calls'])]
                response['object'] = 'chat.completion.chunk'
                response['choices'] = [{'index': 0, 'delta': delta, 'finish_reason': None}]
                final = {**response, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': reason}]}
                raw = ('data: ' + json.dumps(response) + '\n\ndata: ' + json.dumps(final) + '\n\ndata: [DONE]\n\n').encode()
            else:
                raw = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='mkestate-', dir='/tmp') as directory:
            temporary = Path(directory)
            repo = temporary / 'repo'
            repo.mkdir()
            (repo / 'calc.py').write_text('VALUE = 1\n')
            git(['init', '-b', 'main'], repo)
            git(['add', '.'], repo)
            git(['-c', 'user.name=Probe', '-c', 'user.email=probe@example.invalid', 'commit', '-m', 'fixture'], repo)
            data = json.loads((root / 'config/examples/mikasa.json').read_text())
            data.update(runtime=str(temporary / 'state'), members=['member'])
            data['repositories'] = {'local/probe': {'source': str(repo), 'base': 'main', 'checks': []}}
            data['worker'].update(command=[str(root / 'runtime/cache/hermes-venv/bin/python'), 'workers/hermes/bridge.py'],
                                  hermes_source='runtime/cache/hermes-source', timeout=120)
            env = {'MIKASA_MODEL': 'fixture-model', 'MIKASA_MODEL_API_MODE': 'chat_completions',
                   'MIKASA_MODEL_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1',
                   'MIKASA_MODEL_API_KEY': 'synthetic-engineering-key'}
            with patch.dict(os.environ, env):
                config = Config(root, data)
                account, source, python, _ = prepare_profile(config, config.owner)
                member, _, _, _ = prepare_profile(config, 'member')

                def sdk(home, code):
                    result = subprocess.run([str(python), '-c', code], cwd=home,
                        env=clean_env({'HERMES_HOME': str(home), 'PYTHONPATH': os.pathsep.join([str(source), str(root / 'workers/hermes')]),
                                       'HERMES_ENABLE_PROJECT_PLUGINS': '0'}), capture_output=True, text=True, timeout=60)
                    if result.returncode:
                        raise RuntimeError(result.stderr[-2000:])
                    return json.loads(result.stdout.strip().splitlines()[-1])

                checks['native_chat_memory_seeded'] = sdk(account, '''import json
from tools.memory_tool import memory_tool,load_on_disk_store
s=load_on_disk_store()
a=json.loads(memory_tool(action='add',target='memory',content='Chat confirmed convention marker.',store=s))
b=json.loads(memory_tool(action='add',target='user',content='Shared user profile marker.',store=s))
print(json.dumps(a.get('success') and b.get('success')))''')
                task = {'id': 'continuity', 'actor': config.owner, 'payload': {'kind': 'plan', 'repo': 'local/probe'}}
                workspace = Workspace(config, task, 'proof').prepare()
                worker = Worker(config)
                home = config.runtime / 'engineering' / task['id']
                for turn in range(4):
                    step = 0
                    start = len(requests)
                    try:
                        worker.execute(task, {'fixture_turn': turn}, lambda: False, workspace=workspace)
                        checks['turn_' + str(turn)] = turn != 2
                    except ModelFailure as exc:
                        checks['turn_' + str(turn)] = turn == 2 and exc.code == 'invalid_response'
                        if turn != 2:
                            diagnostic = home / 'bridge-failure.json'
                            if diagnostic.exists():
                                print(diagnostic.read_text(), file=sys.stderr)
                            raise
                    first = requests[start]['messages']
                    serialized = json.dumps(first)
                    if turn == 0:
                        checks['chat_memory_and_user_in_engineering_prompt'] = all(m in serialized for m in (
                            'Chat confirmed convention marker.', 'Shared user profile marker.'))
                        checks['identity_skills_injection_proven'] = worker.last_runtime['native_injection']
                        checks['first_turn_has_no_restored_history'] = worker.last_runtime['history_messages'] == 0
                    if turn == 1:
                        checks['tool_history_restored_across_processes'] = all(any(
                            m.get('role') == 'tool' and m.get('tool_call_id') == 'fixture-call-' + str(i) for m in first) for i in range(2))
                        checks['stable_native_session'] = worker.last_runtime['session_id'] == 'mikasa-task-continuity'
                    if turn == 3:
                        checks['failed_result_remains_in_native_history'] = 'invalid result' in serialized
                with sqlite3.connect(home / 'state.db') as db:
                    checks['restored_rows_not_duplicated'] = db.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0] == 4
                    checks['single_task_session'] = db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
                read = "from tools.memory_tool import load_on_disk_store; import json; s=load_on_disk_store(); print(json.dumps((s.format_for_system_prompt('memory') or '')+(s.format_for_system_prompt('user') or '')))"
                checks['engineering_memory_visible_to_new_chat_process'] = 'Engineering confirmed convention marker.' in sdk(account, read)
                checks['other_account_memory_isolated'] = 'marker.' not in sdk(member, read)
                checks['task_transcript_not_in_chat_database'] = not (account / 'state.db').exists()
                # Concurrent native MemoryStore mutations resolve through the shared directory lock.
                task2 = {**task, 'id': 'another-task'}
                with engineering_profile(config, task2, load_skills(root, 'plan'), {'backend': 'docker'}) as home2:
                    parallel = '''import json,os,subprocess,sys
code="from tools.memory_tool import memory_tool,load_on_disk_store; import sys,json; r=json.loads(memory_tool(action='add',target='memory',content=sys.argv[1],store=load_on_disk_store())); assert r.get('success')"
processes=[subprocess.Popen([sys.executable,'-c',code,'Concurrent marker '+str(i)],env={**os.environ,'HERMES_HOME':h},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for i,h in enumerate(HOMES)]
print(json.dumps(all(p.wait(timeout=45)==0 for p in processes)))'''.replace('HOMES', repr([str(home), str(home2)]))
                    checks['concurrent_native_writes_succeed'] = sdk(home, parallel)
                memory = sdk(account, read)
                checks['concurrent_native_writes_retained'] = all('Concurrent marker ' + str(i) in memory for i in range(2))
                # Publish an actual native compression continuation, then resume through our bridge.
                checks['compression_child_published'] = sdk(home, '''import json
from hermes_state import SessionDB
d=SessionDB(); d.reopen_session('mikasa-task-continuity')
d.publish_compression_child(parent_session_id='mikasa-task-continuity',child_session_id='compressed-child',source='cli',
 messages=[{'role':'user','content':'Compressed context marker.'},{'role':'assistant','content':'Compressed response marker.'}],require_compression_lease=False)
d.close(); print(json.dumps(True))''')
                turn, step = 4, 0
                start = len(requests)
                worker.execute(task, {'fixture_turn': turn}, lambda: False, workspace=workspace)
                history = json.dumps(requests[start]['messages'])
                checks['compression_tip_resumed_without_parent_replay'] = (
                    worker.last_runtime['session_id'] == 'compressed-child'
                    and worker.last_runtime['history_messages'] == 2
                    and 'Compressed context marker.' in history and 'fixture-call-0' not in history)
                config.data['repositories']['local/probe'].update(
                    check_image=IMAGE, checks=[['python', '-c', 'from calc import VALUE; assert VALUE == 2']])
                service = Service(config)
                for scenario in ('repair', 'unfinished', 'regressed'):
                    step, start = 0, len(requests)
                    task = service.submit({'kind': 'implement', 'repo': 'local/probe', 'title': scenario,
                                           'acceptance': 'VALUE equals 2'}, config.owner, scenario)
                    finished = service.run_once()
                    checks[scenario + '_native_kanban_lease'] = (finished['native_id'].startswith('t_')
                        and finished['native_status'] == ('review' if scenario == 'repair' else 'blocked'))
                    result = finished.get('result') or {}
                    checks[scenario + '_expected_outcome'] = finished['state'] == ('awaiting_review' if scenario == 'repair' else 'blocked')
                    if not result:
                        raise RuntimeError('Implementation probe failed: ' + str(finished.get('error')))
                    events = [e['data'] for e in service.tasks.events(task['id']) if e['kind'] == 'execution']
                    checks[scenario + '_one_worker_invocation'] = len([e for e in events if e.get('phase') == 'worker' and e['status'] == 'started']) == 1
                    checks[scenario + '_one_final_validation'] = len([e for e in events if e.get('phase') == 'validation' and e['status'] == 'completed']) == 1
                    codes = [c['code'] for e in result['execution']['tool_events'] for c in e.get('checks', [])]
                    if scenario == 'repair':
                        checks['native_red_green_repair'] = len(codes) == 2 and codes[0] != 0 and codes[1] == 0
                        checks['same_conversation_observes_failed_check'] = any(m.get('role') == 'tool' and 'AssertionError' in str(m.get('content')) for m in requests[-1]['messages'])
                        checks['repaired_tree_committed'] = (git(['show', 'HEAD:calc.py'], result['workspace']) == 'VALUE = 2'
                                                             and result['head'] != result['base'])
                    else:
                        checks[scenario + '_no_commit_on_failure'] = (result['checks'][0]['code'] != 0
                            and git(['rev-parse', 'HEAD'], result['workspace']) == result['base'])
                        checks[scenario + '_no_automatic_requeue'] = service.run_once() is None
                    if scenario == 'regressed':
                        checks['final_check_rejects_changes_after_green_tool_check'] = codes == [0] and result['checks'][0]['code'] != 0
                checks['implementation_identity_and_skills_loaded'] = result['execution']['native_injection']
                remaining = subprocess.check_output(['docker', 'ps', '-aq'], text=True).split()
                checks['bridge_containers_removed'] = bool(containers) and not set(containers) & set(remaining)
                checks['synthetic_key_not_saved'] = not any(env['MIKASA_MODEL_API_KEY'].encode() in p.read_bytes()
                    for p in config.runtime.rglob('*') if p.is_file() and not p.is_symlink())
        print(json.dumps({'hermes_revision': HERMES_REVISION, 'checks': checks, 'passed': all(checks.values())}, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


if __name__ == '__main__':
    raise SystemExit(main())
