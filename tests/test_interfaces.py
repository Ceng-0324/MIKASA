import hashlib
import hmac
import http.client
import json
import os
import threading
from unittest.mock import patch

from mikasa.errors import Conflict, Forbidden, MikasaError
from mikasa.github import GitHub
from mikasa.server import authenticate, make_server
from tests.support import BaseTest, REPO, SHA


class InterfaceTests(BaseTest):
    def test_token_actor_cannot_be_spoofed(self):
        with patch.dict(os.environ, {"MIKASA_OWNER_API_TOKEN": "o" * 32}):
            self.assertEqual(authenticate(self.config, "Bearer " + "o" * 32), self.config.owner)
            for header in ("", "Bearer Ceng-0324", "Bearer wrong"):
                with self.assertRaises(Forbidden):
                    authenticate(self.config, header)

    def test_retired_engineering_routes_never_dispatch(self):
        with patch.dict(os.environ, {'MIKASA_OWNER_API_TOKEN': 'o' * 32}):
            server = make_server(self.config, '127.0.0.1', 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                headers = {'Authorization': 'Bearer ' + 'o' * 32}
                for method, path, auth, expected in (
                    ('GET', '/tasks', {}, 403), ('GET', '/tasks', headers, 410),
                    ('POST', '/tasks', headers, 410), ('POST', '/tasks/old/publish', headers, 410),
                    ('POST', '/webhooks/github', {}, 410)):
                    connection.request(method, path, '{}' if method == 'POST' else None, auth)
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    response.read()
                connection.close()
                self.assertFalse((self.config.runtime / 'kanban').exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)
