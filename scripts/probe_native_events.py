#!/usr/bin/env python3
"""Actual pinned Gateway/SSE with a local model fixture and disposable profiles."""
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.errors import MikasaError
from mikasa.native import HERMES_REVISION, NativeGateway
from mikasa.run_events import RunEvents
from mikasa.store import Store
from mikasa.backup import backup_state, restore_state


def main():
    root = Path(__file__).resolve().parents[1]
    checks, observed, requests = {}, [], []
    held, release = threading.Event(), threading.Event()
    subscribing = threading.Event()

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            messages = body.get('messages', [])
            primary = bool(body.get('tools'))
            prompt = json.dumps(messages)
            if primary:
                requests.append(body)
            if primary and 'EVENT_PROBE_HOLD' in prompt:
                held.set()
                release.wait(45)
            tool_done = any(m.get('role') == 'tool' for m in messages)
            if primary and 'EVENT_PROBE_SUCCESS' in prompt and not tool_done:
                # Synchronize the fixture, so fast machines cannot finish the
                # run before the initial status read has admitted an SSE wait.
                if not subscribing.wait(10):
                    self.send_error(500)
                    return
                message, reason = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'event-probe-memory', 'type': 'function', 'function': {
                        'name': 'memory', 'arguments': json.dumps({'action': 'add', 'target': 'memory',
                                                                 'content': 'Event probe memory marker.'})}}]}, 'tool_calls'
            else:
                message, reason = {'role': 'assistant', 'content': 'Native event probe reply.'}, 'stop'
            response = {'id': 'fixture-response', 'object': 'chat.completion', 'created': 1,
                        'model': 'fixture-model', 'choices': [{'index': 0, 'message': message, 'finish_reason': reason}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}}
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
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    class ObserveEvents(RunEvents):
        def __enter__(self):
            result = super().__enter__()
            subscribing.set()
            return result

        def __exit__(self, *args):
            super().__exit__(*args)
            observed.append({'status': self.http_status, 'terminal': self.terminal, 'joined': not self.thread.is_alive()})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='mkevents-', dir='/tmp') as directory:
            data = json.loads((root / 'config/examples/mikasa.json').read_text())
            data.update(runtime=str(Path(directory) / 'runtime'))
            data['worker']['timeout'] = 40
            config = Config(root, data)
            Store(config.runtime)
            env = {'MIKASA_MODEL': 'fixture-model', 'MIKASA_MODEL_API_MODE': 'chat_completions',
                   'MIKASA_MODEL_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1',
                   'MIKASA_MODEL_API_KEY': 'synthetic-events-model-key'}
            with patch.dict(os.environ, env), patch('mikasa.native.RunEvents', ObserveEvents):
                with NativeGateway(config, config.owner) as gateway:
                    session = uuid.uuid4().hex
                    gateway.create(session, 'fixture-model')
                    run = gateway.start(session, 'EVENT_PROBE_SUCCESS', 'fixture-model', 'event-success')
                    result = gateway.wait(run['run_id'])
                    checks['native_sse_terminal'] = any(e['status'] == 200 and e['terminal'] == 'run.completed' for e in observed)
                    checks['durable_reply'] = result['status'] == 'completed' and result['output'] == 'Native event probe reply.'
                    checks['identity_policy_skills_evidence'] = all(result.get('runtime', {}).get(k) for k in (
                        'identity', 'policy', 'persona_skill', 'skills_index'))
                    home, key = gateway.home, gateway.key
                    checks['native_memory_written'] = 'Event probe memory marker.' in (home / 'memories/MEMORY.md').read_text()
                    rows = gateway.messages(session)['data']
                    checks['native_tool_history'] = any(m.get('role') == 'tool' for m in rows)
                    count, streams = len(requests), len(observed)
                    replay = gateway.start(session, 'EVENT_PROBE_SUCCESS', 'fixture-model', 'event-success')
                    again = gateway.wait(replay['run_id'])
                    checks['receipt_replay_without_new_stream_or_inference'] = (
                        replay['run_id'] == run['run_id'] and again == result and len(requests) == count and len(observed) == streams)

                    cancel_session = uuid.uuid4().hex
                    gateway.create(cancel_session, 'fixture-model')
                    cancel_run = gateway.start(cancel_session, 'EVENT_PROBE_HOLD', 'fixture-model', 'event-cancel')
                    try:
                        gateway.wait(cancel_run['run_id'], held.is_set)
                    except MikasaError:
                        checks['pause_returns_error'] = held.is_set()
                    else:
                        checks['pause_returns_error'] = False
                    release.set()
                    deadline = time.monotonic() + 15
                    stop = gateway.request('GET', '/v1/runs/' + cancel_run['run_id'])
                    while stop['status'] not in {'completed', 'cancelled', 'failed', 'interrupted'} and time.monotonic() < deadline:
                        time.sleep(.1)
                        stop = gateway.request('GET', '/v1/runs/' + cancel_run['run_id'])
                    checks['native_stop_observed'] = stop['status'] in {'cancelled', 'interrupted'}
                    checks['all_stream_readers_joined'] = all(e['joined'] for e in observed)

                backup = Path(directory) / 'backup'
                restored = Path(directory) / 'restored'
                backup_state(config, backup)
                restore_state(config, backup, restored)
                data['runtime'] = str(restored)
                config = Config(root, data)
                count, streams = len(requests), len(observed)
                with NativeGateway(config, config.owner) as gateway:
                    restarted = gateway.wait(run['run_id'])
                    checks['restart_recovers_durable_result_without_stream'] = (
                        restarted == result and len(observed) == streams and len(requests) == count)
                    checks['profile_key_and_history_preserved'] = gateway.key == key and gateway.messages(session)['data'] == rows
                    checks['restored_profile_memory_preserved'] = 'Event probe memory marker.' in (gateway.home / 'memories/MEMORY.md').read_text()
                    try:
                        gateway.wait(cancel_run['run_id'])
                    except MikasaError:
                        checks['cancelled_run_not_restarted'] = len(requests) == count
                    else:
                        checks['cancelled_run_not_restarted'] = False
                checks['no_model_key_persisted'] = not any(env['MIKASA_MODEL_API_KEY'].encode() in p.read_bytes()
                    for p in Path(directory).rglob('*') if p.is_file() and not p.is_symlink())
                checks['no_reader_threads_left'] = not any(t.name == 'mikasa-run-events' for t in threading.enumerate())
        print(json.dumps({'hermes_revision': HERMES_REVISION, 'checks': checks, 'passed': all(checks.values())}, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    raise SystemExit(main())
