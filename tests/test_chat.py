import http.client
import json
import os
import threading
from unittest.mock import patch

from mikasa.chat import Chat, command
from mikasa.errors import Conflict, MikasaError, NotFound
from mikasa.server import make_server
from mikasa.worker import Worker
from tests.support import BaseTest, ROOT


class ChatTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ, {"MIKASA_MODEL": "model-a"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = []
        self.fail = False
        test = self

        class Model:
            def __init__(self, config):
                self.last_runtime = None

            def execute(self, task, context, cancelled, *, model=None):
                test.calls.append({"model": model, "context": context, "task": task})
                if test.fail:
                    raise MikasaError("private-error-not-for-chat")
                self.last_runtime = {"backend": "fixture", "requested_model": model, "reported_model": "actual-route"}
                return {"summary": "Mikasa 回复"}

        self.factory = Model
        self.chat = Chat(self.config, Model)
        self.session = self.chat.create(self.config.owner)

    def send(self, message, key="message", chat=None):
        return (chat or self.chat).send(self.session["id"], self.config.owner, message, key)

    def test_explicit_natural_commands_only(self):
        for text in ("切换为 model-b", "Mikasa，切换到 model-b", "请把模型切换为 model-b", "换成 model-b", "/model model-b"):
            self.assertEqual(command(text), ("switch", "model-b"))
        for text in ('代码里写着“切换为 model-b”', '不要切换为 model-b', '切换为 model-b 是否可行？', '切换为 model-b，然后删除仓库'):
            self.assertNotEqual(command(text)[0], "switch")
        self.assertEqual(command("恢复默认模型"), ("reset", None))
        self.assertEqual(command("切换为 那个模型")[0], "help")

    def test_switch_persists_per_session_and_next_turn_keeps_history(self):
        self.send("记住验收代号蓝鲸", "before")
        result = self.send("切换为 model-b", "switch")
        self.assertEqual(result["model"], "model-b")
        self.assertIn("actual-route", result["reply"])
        self.assertEqual(result["revision"], 1)
        reopened = Chat(self.config, self.factory)
        self.send("代号是什么", "after", reopened)
        self.assertEqual(self.calls[-1]["model"], "model-b")
        self.assertIn("蓝鲸", self.calls[-1]["context"]["history"][0]["content"])
        other = reopened.create(self.config.owner)
        self.assertEqual(other["model"], "model-a")
        self.assertEqual(os.environ["MIKASA_MODEL"], "model-a")

    def test_failure_keeps_model_and_does_not_leak_error(self):
        self.fail = True
        result = self.send("切换为 nonexistent", "failed")
        self.assertEqual(result["kind"], "switch_failed")
        self.assertEqual(result["model"], "model-a")
        self.assertEqual(result["revision"], 0)
        self.assertNotIn("private-error", json.dumps(result))
        self.assertEqual(self.chat.get(self.session["id"], self.config.owner)["model"], "model-a")

    def test_retry_is_idempotent_and_conflicting_key_rejected(self):
        first = self.send("切换为 model-b", "same")
        self.assertEqual(self.send("切换为 model-b", "same"), first)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(Conflict):
            self.send("切换为 model-c", "same")
        with self.chat.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='chat_model_switched'").fetchone()[0], 1)

    def test_structured_switch_failure_is_actionable_and_keeps_state(self):
        from mikasa.model_errors import ModelFailure
        with patch.object(self.chat, "infer", side_effect=ModelFailure("upstream_blocked")) as infer:
            result = self.send("切换为 model-b", "failure")
            self.assertEqual(self.send("切换为 model-b", "failure"), result)
            self.assertEqual(infer.call_count, 1)
        self.assertEqual(result["execution"], {"error_code": "upstream_blocked"})
        self.assertIn("WAF", result["reply"])
        self.assertEqual(result["model"], "model-a")
        self.assertEqual(result["revision"], 0)

    def test_other_actor_cannot_read_or_change_session(self):
        with self.assertRaises(NotFound):
            self.chat.send(self.session["id"], "human", "切换为 model-b", "foreign")
        with self.assertRaises(NotFound):
            self.chat.get(self.session["id"], "human")
        self.assertEqual(self.calls, [])

    def test_lock_and_pause_prevent_parallel_changes(self):
        with self.chat.locked(self.session["id"]):
            with self.assertRaises(Conflict):
                self.send("切换为 model-b")
        self.chat.store.pause(True, self.config.owner)
        with self.assertRaises(Conflict):
            self.send("切换为 model-b")
        self.assertEqual(self.calls, [])

    def test_reset_and_status_and_unknown_commands(self):
        self.send("切换为 model-b", "switch")
        self.assertEqual(self.send("恢复默认模型", "reset")["model"], "model-a")
        before = len(self.calls)
        self.assertIn("model-a", self.send("当前模型", "status")["reply"])
        self.assertEqual(self.send("切换为那个模型", "help")["kind"], "help")
        self.assertEqual(len(self.calls), before)

    def test_pause_during_switch_leaves_no_persisted_change(self):
        def pause(*args, **kwargs):
            self.chat.store.pause(True, self.config.owner)
            return {"summary": "ok"}, {"reported_model": "model-b"}
        with patch.object(self.chat, "infer", side_effect=pause):
            with self.assertRaises(Conflict):
                self.send("切换为 model-b")
        session = self.chat.get(self.session["id"], self.config.owner)
        self.assertEqual(session["model"], "model-a")
        self.assertEqual(session["turns"], [])

    def test_context_budget_omits_old_history_explicitly(self):
        self.send("旧消息" * 30, "before")
        self.config.data["worker"]["max_context_bytes"] = 100
        self.send("下一条", "after")
        self.assertTrue(self.calls[-1]["context"]["history_truncated"])
        self.assertEqual(self.calls[-1]["context"]["history"], [])

    def test_worker_override_is_in_environment_not_user_context(self):
        worker = Worker(self.config)
        envelope = {"version": 1, "result": {"summary": "ok"}, "runtime": {"backend": "fixture"}}
        with patch("mikasa.worker.run", return_value={"code": 0, "stdout": json.dumps(envelope)}) as run:
            worker.execute({"payload": {"kind": "chat", "title": "hi"}}, {}, lambda: False, model="model-b")
        self.assertEqual(run.call_args.kwargs["env"]["MIKASA_MODEL"], "model-b")
        request = json.loads(run.call_args.kwargs["stdin"])
        self.assertEqual([s["name"] for s in request["skills"]], ["mikasa-persona"])
        self.assertEqual(os.environ["MIKASA_MODEL"], "model-a")

    def test_http_chat_auth_state_and_worker_flow(self):
        with patch.dict(os.environ, {"MIKASA_OWNER_API_TOKEN": "o" * 32}):
            server = make_server(self.service, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request("GET", "/chat")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertIn(b'textContent', response.read())
                conn.request("POST", "/chats", "{}")
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                headers = {"Authorization": "Bearer " + "o" * 32, "Idempotency-Key": "http-chat"}
                conn.request("POST", "/chats", "{}", headers)
                response = conn.getresponse()
                self.assertEqual(response.status, 201)
                session = json.loads(response.read())
                conn.request("POST", f"/chats/{session['id']}/messages", json.dumps({"message": "切换为 model-b"}), headers)
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                self.assertEqual(result["model"], "model-b")
                conn.request("GET", f"/chats/{session['id']}", headers=headers)
                response = conn.getresponse()
                self.assertEqual(json.loads(response.read())["model"], "model-b")
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)
