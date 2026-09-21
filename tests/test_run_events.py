"""Local HTTP protocol tests: event notification, durable recovery and teardown."""
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from mikasa.errors import MikasaError
from mikasa.native import NativeAPIError, NativeGateway
from mikasa.run_events import MAX_FRAME_BYTES


class RunEventTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='mikasa-events-')
        self.addCleanup(temp.cleanup)
        self.paths, self.status = [], 'running'
        self.stream_open, self.release = threading.Event(), threading.Event()
        self.stream_status, self.stop_status = 200, 200
        self.behavior = lambda handler: self.release.wait(10)
        self.on_status = lambda: None
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case.paths.append(('GET', self.path))
                if self.headers.get('Authorization') != 'Bearer synthetic-api-key':
                    self.send_error(401)
                    return
                if self.path.endswith('/events'):
                    if case.stream_status != 200:
                        self.send_error(case.stream_status, 'synthetic-secret-do-not-reflect')
                        return
                    try:
                        case.behavior(self)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                else:
                    case.on_status()
                    self.reply({'run_id': 'run-test', 'status': case.status, 'output': 'durable reply',
                                'runtime': {'model': 'fixture-model'}, 'error': 'synthetic-secret-do-not-reflect'})

            def do_POST(self):
                case.paths.append(('POST', self.path))
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                case.status = 'cancelled'
                case.release.set()
                if case.stop_status == 200:
                    self.reply({'status': 'stopping'})
                else:
                    self.send_error(case.stop_status, 'synthetic-secret-do-not-reflect')

            def reply(self, obj):
                raw = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def stream(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.end_headers()
                case.stream_open.set()

            def frame(self, name, **values):
                self.wfile.write(('data: ' + json.dumps({'run_id': 'run-test', 'event': name, **values}) + '\n\n').encode())
                self.wfile.flush()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            self.release.set()
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(close)
        gateway = self.gateway = NativeGateway.__new__(NativeGateway)
        gateway.config = SimpleNamespace(data={'worker': {'timeout': 5}})
        gateway.url = f'http://127.0.0.1:{server.server_port}'
        gateway.key = 'synthetic-api-key'
        gateway.home = Path(temp.name)
        gateway.http = build_opener(ProxyHandler({}))

    def assert_closed(self):
        self.assertFalse(any(t.name == 'mikasa-run-events' for t in threading.enumerate()))
        self.assertTrue(all(method != 'POST' or path.endswith('/stop') for method, path in self.paths))

    def test_api_error_closes_response_without_reading_private_body(self):
        body = io.BytesIO(b'private upstream error')
        error = HTTPError(self.gateway.url, 403, 'forbidden', {}, body)
        with patch.object(self.gateway.http, 'open', side_effect=error):
            with self.assertRaises(NativeAPIError) as raised:
                self.gateway.request('GET', '/v1/runs/run-test')
        self.assertEqual(raised.exception.status, 403)
        self.assertTrue(body.closed)
        self.assertNotIn('private', str(raised.exception))

    def test_events_wake_without_polling_and_result_comes_from_durable_state(self):
        counts = []
        def stream(handler):
            handler.stream()
            handler.wfile.write(b': keepalive\r\n\r\nid: ignored\r\nevent: message\r\ndata: {"run_id": "run-test",\r\ndata: "event":"message.delta","delta":"hello"}\r\n\r\n')
            handler.wfile.flush()
            self.release.wait(.4)
            counts.append(len([p for m, p in self.paths if not p.endswith('/events')]))
            self.status = 'completed'
            # Deliberately keep the transport open after terminal notification.
            handler.frame('run.completed', output='not the authoritative reply')
            self.release.wait(10)
        self.behavior = stream
        evidence = self.gateway.home / 'request-evidence' / (hashlib.sha256(b'run-test').hexdigest() + '.json')
        evidence.parent.mkdir()
        evidence.write_text(json.dumps({'identity': True, 'persona_skill': True, 'api_mode': 'chat_completions'}))
        result = self.gateway.wait('run-test')
        self.assertEqual(result['output'], 'durable reply')
        self.assertTrue(result['runtime']['identity'])
        self.assertEqual(counts, [1])
        self.assertEqual(len(self.paths), 3)  # Initial status, one SSE, final status.
        self.assert_closed()

    def test_completed_receipt_needs_no_stream(self):
        self.status = 'completed'
        self.assertEqual(self.gateway.wait('run-test')['output'], 'durable reply')
        self.assertEqual(self.paths, [('GET', '/v1/runs/run-test')])
        self.assert_closed()

    def test_lost_transport_recovers_same_run_without_resubscription(self):
        def stream(handler):
            handler.stream()
            handler.frame('message.delta', delta='unpersisted fragment')
        self.behavior = stream
        def status():
            if len([p for m, p in self.paths if not p.endswith('/events')]) >= 3:
                self.status = 'completed'
        self.on_status = status
        self.assertEqual(self.gateway.wait('run-test')['output'], 'durable reply')
        self.assertEqual(sum(p.endswith('/events') for m, p in self.paths), 1)
        self.assert_closed()

    def test_retired_stream_404_uses_persisted_completion(self):
        self.stream_status = 404
        def status():
            if len(self.paths) > 1:
                self.status = 'completed'
        self.on_status = status
        self.assertEqual(self.gateway.wait('run-test')['status'], 'completed')
        self.assert_closed()

    def test_silent_stream_pause_stops_once_and_joins_reader(self):
        def stream(handler):
            handler.stream()
            self.release.wait(10)
        self.behavior = stream
        with self.assertRaisesRegex(MikasaError, '暂停'):
            self.gateway.wait('run-test', self.stream_open.is_set)
        self.assertEqual(sum(m == 'POST' for m, p in self.paths), 1)
        self.assert_closed()

    def test_timeout_interrupts_stalled_headers_and_reports_stop_failure(self):
        self.gateway.config.data['worker']['timeout'] = .3
        self.stop_status = 503
        started = time.monotonic()
        with self.assertRaises(NativeAPIError) as caught:
            self.gateway.wait('run-test')
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn('synthetic-secret', str(caught.exception))
        self.assertLess(time.monotonic() - started, 3)
        self.assert_closed()

    def test_timeout_stops_once_when_stream_has_disappeared(self):
        self.stream_status = 404
        self.gateway.config.data['worker']['timeout'] = .3
        with self.assertRaisesRegex(MikasaError, '已请求取消'):
            self.gateway.wait('run-test')
        self.assertEqual(sum(m == 'POST' for m, p in self.paths), 1)
        self.assert_closed()

    def test_pause_of_already_completed_run_does_not_send_stop(self):
        self.status = 'completed'
        with self.assertRaisesRegex(MikasaError, '暂停'):
            self.gateway.wait('run-test', lambda: True)
        self.assertEqual(self.paths, [('GET', '/v1/runs/run-test')])
        self.assert_closed()

    def test_terminal_failures_are_not_restarted_or_exposed(self):
        for state in ('failed', 'cancelled', 'interrupted'):
            with self.subTest(state=state):
                self.status = 'running'
                def stream(handler):
                    handler.stream()
                    self.status = state
                    handler.frame('run.' + state)
                self.behavior = stream
                with self.assertRaisesRegex(MikasaError, '未重新发起请求') as caught:
                    self.gateway.wait('run-test')
                self.assertNotIn('synthetic-secret', str(caught.exception))
                self.assert_closed()

    def test_malformed_or_oversized_stream_recovers_without_retaining_events(self):
        for raw in (b'data: invalid\n\n', b'data: ' + b'x' * (MAX_FRAME_BYTES + 1),
                    b'data: {"run_id":"other","event":"run.completed"}\n\n'):
            with self.subTest(length=len(raw)):
                self.status = 'running'
                def stream(handler):
                    handler.stream()
                    self.status = 'completed'
                    handler.wfile.write(raw)
                    handler.wfile.flush()
                self.behavior = stream
                self.assertEqual(self.gateway.wait('run-test')['output'], 'durable reply')
                self.assert_closed()

    def test_stream_auth_error_does_not_degrade_to_polling(self):
        self.stream_status = 403
        with self.assertRaises(NativeAPIError) as caught:
            self.gateway.wait('run-test')
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.paths), 2)
        self.assert_closed()
