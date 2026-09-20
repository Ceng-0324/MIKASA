import hashlib
import hmac
import http.client
import json
import os
import threading
from unittest.mock import patch

from mikasa.errors import Conflict, Forbidden, MikasaError
from mikasa.github import GitHub
from mikasa.server import authenticate, make_server, webhook
from tests.support import BaseTest, FakeGitHub, REPO, SHA


class InterfaceTests(BaseTest):
    def test_token_actor_cannot_be_spoofed(self):
        with patch.dict(os.environ, {"MIKASA_OWNER_API_TOKEN": "o" * 32}):
            self.assertEqual(authenticate(self.config, "Bearer " + "o" * 32), self.config.owner)
            for header in ("", "Bearer Ceng-0324", "Bearer wrong"):
                with self.assertRaises(Forbidden):
                    authenticate(self.config, header)

    def test_webhook_signature_replay_repo_boundary(self):
        raw = json.dumps({"repository": {"full_name": REPO}, "action": "opened", "number": 1}).encode()
        secret = "webhook-test-only"
        headers = {"X-GitHub-Delivery": "delivery-1", "X-GitHub-Event": "pull_request",
                   "X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}
        with patch.dict(os.environ, {"MIKASA_GITHUB_WEBHOOK_SECRET": secret}):
            self.assertFalse(webhook(self.service, headers, raw)["duplicate"])
            self.assertTrue(webhook(self.service, headers, raw)["duplicate"])
            with self.assertRaises(Forbidden):
                webhook(self.service, headers, raw + b" ")
            foreign = json.dumps({"repository": {"full_name": "elsewhere/foreign"}}).encode()
            headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(secret.encode(), foreign, hashlib.sha256).hexdigest()
            with self.assertRaises(MikasaError):
                webhook(self.service, headers, foreign)

    def test_http_submit_query_and_cancel(self):
        with patch.dict(os.environ, {"MIKASA_OWNER_API_TOKEN": "o" * 32}):
            server = make_server(self.service, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", "/tasks")
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                headers = {"Authorization": "Bearer " + "o" * 32, "Content-Type": "application/json", "Idempotency-Key": "http-test"}
                payload = {"kind": "audit", "repo": REPO, "title": "Audit", "acceptance": "Report evidence"}
                connection.request("POST", "/tasks", json.dumps(payload), headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                task = json.loads(response.read())
                connection.request("GET", f"/tasks/{task['id']}", headers=headers)
                response = connection.getresponse()
                self.assertEqual(json.loads(response.read())["state"], "queued")
                connection.request("POST", f"/tasks/{task['id']}/cancel", "{}", headers)
                response = connection.getresponse()
                self.assertEqual(json.loads(response.read())["state"], "cancelled")
                connection.request("POST", "/tasks", "[]", headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_gate_requires_correct_reviewer_and_current_sha(self):
        adapter = self.github
        self.service.store.provenance(REPO, 1, SHA, "human", self.config.owner)
        adapter.reviews = [{"user": {"login": self.config.bot}, "state": "APPROVED", "commit_id": "c" * 40}]
        gate = GitHub.gate(adapter_with_config(adapter, self.config), REPO, 1, self.service.store)
        self.assertFalse(gate["allowed"])
        adapter.reviews[0]["commit_id"] = SHA
        self.assertTrue(GitHub.gate(adapter, REPO, 1, self.service.store)["allowed"])
        adapter.reviews.append({"user": {"login": self.config.bot}, "state": "CHANGES_REQUESTED", "commit_id": SHA})
        self.assertFalse(GitHub.gate(adapter, REPO, 1, self.service.store)["allowed"])

    def test_gate_unknown_authorship_and_bot_self_approval(self):
        adapter = adapter_with_config(self.github, self.config)
        adapter.reviews = [{"user": {"login": self.config.bot}, "state": "APPROVED", "commit_id": SHA}]
        self.assertFalse(GitHub.gate(adapter, REPO, 1, self.service.store)["allowed"])
        adapter.current["user"]["login"] = self.config.bot
        gate = GitHub.gate(adapter, REPO, 1, self.service.store)
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["required_reviewer"], self.config.owner)
        adapter.reviews.append({"user": {"login": self.config.owner}, "state": "APPROVED", "commit_id": SHA})
        self.assertTrue(GitHub.gate(adapter, REPO, 1, self.service.store)["allowed"])

    def test_cannot_record_bot_pr_as_human(self):
        self.github.current["user"]["login"] = self.config.bot
        with self.assertRaises(Forbidden):
            self.service.record_provenance(REPO, 1, SHA, "human", self.config.owner)

    def test_publish_rejects_stale_review(self):
        task = self.submit("review", pr=1)
        _, token = self.service.store.claim(self.config.bot)
        self.service.store.finish(task["id"], token, "done", {
            "summary": "Review", "head": SHA, "base": "c" * 40, "verdict": "APPROVED"})
        with self.assertRaises(Conflict):
            self.service.publish(task["id"], self.config.owner)
        self.assertEqual(self.github.writes, [])

    def test_github_missing_credentials_and_publish_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MikasaError):
                GitHub(self.config).request("GET", "/user")
        with self.assertRaises(Forbidden):
            GitHub(self.config).verify_publisher()


def adapter_with_config(adapter, config):
    adapter.config = config
    return adapter
