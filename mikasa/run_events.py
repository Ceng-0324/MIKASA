"""One cancellable consumer of the pinned Gateway's non-replayable SSE queue."""
import http.client
import json
import socket
import threading
from urllib.parse import urlsplit

TERMINAL = frozenset({'completed', 'failed', 'cancelled', 'interrupted'})
MAX_FRAME_BYTES = 1_048_576


class RunEvents:
    """Wake a waiter on terminal/EOF; never keep transcripts or replay a run.

    A reader thread lets pause/deadline checks proceed during a quiet stream.
    Closing shuts down its socket before joining, including stalled headers.
    """
    def __init__(self, url, key, run_id):
        endpoint = urlsplit(url)
        if endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1':
            raise ValueError('Run events require the isolated loopback Gateway')
        self.connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=2)
        self.key, self.run_id = key, run_id
        self.done = threading.Event()
        self.stopped = threading.Event()
        self.http_status = None
        self.terminal = None
        self.socket = None
        self.thread = threading.Thread(target=self._read, name='mikasa-run-events')

    def __enter__(self):
        self.thread.start()
        return self

    def _read(self):
        try:
            self.connection.connect()
            self.socket = self.connection.sock
            if self.stopped.is_set():
                return
            # Native keepalive is 10s. A dead transport falls back to durable
            # status; cancellation interrupts this socket without waiting 30s.
            self.socket.settimeout(30)
            self.connection.request('GET', '/v1/runs/' + self.run_id + '/events', headers={
                'Authorization': 'Bearer ' + self.key, 'Accept': 'text/event-stream'})
            with self.connection.getresponse() as response:
                self.http_status = response.status
                if response.status != 200 or response.getheader('Content-Type', '').split(';')[0].strip() != 'text/event-stream':
                    return
                data, size = [], 0
                while not self.stopped.is_set():
                    line = response.readline(MAX_FRAME_BYTES + 1)
                    if not line:
                        return
                    size += len(line)
                    if size > MAX_FRAME_BYTES:
                        return  # Bound memory even for incomplete/malformed frames.
                    line = line.rstrip(b'\r\n')
                    if not line:
                        if data:
                            event = json.loads(b'\n'.join(data))
                            if not isinstance(event, dict) or event.get('run_id') != self.run_id:
                                return
                            name = event.get('event')
                            if isinstance(name, str) and name.startswith('run.') and name[4:] in TERMINAL:
                                self.terminal = name
                                return
                        data, size = [], 0
                    elif line.startswith(b'data:'):
                        value = line[5:]
                        data.append(value[1:] if value.startswith(b' ') else value)
                    # SSE comments, event/id/retry fields are not a replay API.
        except (OSError, http.client.HTTPException, ValueError):
            # No upstream text, prompts, deltas or credentials escape this layer.
            pass
        finally:
            self.connection.close()
            self.done.set()

    def __exit__(self, *args):
        self.stopped.set()
        if self.socket is not None:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # connect is bounded by 2s; every later blocking read is interruptible.
        self.thread.join()
