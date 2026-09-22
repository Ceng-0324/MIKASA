import io
import json
import os
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

from mikasa.errors import MikasaError
from mikasa.github import GitHub
from mikasa.process import clean_env, run
from mikasa.skills import load_skills
from tests.support import BaseTest, REPO, ROOT, SHA


class AdapterTests(BaseTest):


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
