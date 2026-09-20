import http.client
import io
import json
import os
import threading
from contextlib import redirect_stdout
from unittest.mock import patch

from mikasa.chat import Chat, command
from mikasa.errors import Conflict, MikasaError, NotFound
from mikasa.server import make_server
from mikasa.worker import Worker
from tests.support import BaseTest, command_reply
from tests.native_support import Gateways


class ChatTests(BaseTest):
    def setUp(self):
        super().setUp()
        for context in (patch.object(Worker, "command", side_effect=command_reply),
                        patch.dict(os.environ, {"MIKASA_MODEL": "model-a"})):
            context.start()
            self.addCleanup(context.stop)
        self.gateways = Gateways()
        self.chat = Chat(self.config, self.gateways)
        self.session = self.chat.create(self.config.owner)
        self.gateway = self.gateways.for_actor(self.config.owner)

    def send(self, message, key="message", chat=None):
        return (chat or self.chat).send(self.session["id"], self.config.owner, message, key)

    def test_explicit_natural_commands_only(self):
        for text in ("切换为 model-b", "Mikasa，切换到 model-b", "请把模型切换为 model-b", "/model model-b"):
            self.assertEqual(command(text, command_reply)["target"], "model-b")
        for text in ('代码里写着“切换为 model-b”', '不要切换为 model-b', '切换为 model-b 是否可行？', '切换为 model-b，然后删除仓库'):
            self.assertNotEqual(command(text, command_reply)["kind"], "switch")

    def test_new_idempotent_preserves_model_and_old_native_history(self):
        self.send("记住蓝鲸", "remember")
        self.send("切换为 model-b", "switch")
        calls = len(self.gateway.calls)
        result = self.send("/new", "new")
        self.assertEqual(self.send("/new", "new"), result)
        self.assertEqual(len(self.gateway.calls), calls)
        self.assertNotEqual(result["chat_id"], self.session["id"])
        self.assertEqual(result["model"], "model-b")
        reopened = Chat(self.config, self.gateways)
        self.assertEqual(reopened.get(result["chat_id"], self.config.owner)["turns"], [])
        old = reopened.get(self.session["id"], self.config.owner)
        self.assertEqual(len(old["turns"]), 1)
        self.assertEqual(old["turns"][0]["message"], "记住蓝鲸")
        with self.assertRaises(NotFound):
            reopened.get(result["chat_id"], "human")

    def test_new_pause_and_lock(self):
        with self.chat.locked(self.session["id"]), self.assertRaises(Conflict):
            self.send("/new")
        def pause(text, cancelled):
            self.chat.store.pause(True, self.config.owner)
            return command_reply(text)
        with patch.object(Worker, "command", side_effect=pause), self.assertRaises(Conflict):
            self.send("/new")
        with self.chat.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_links").fetchone()[0], 1)

    def test_no_mirrored_transcript_or_control_messages(self):
        self.send("/model", "menu")
        self.send("/init", "deferred")
        self.send("私有用户消息", "next")
        with self.chat.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0], 0)
            records = [dict(r) for r in db.execute("SELECT * FROM chat_requests")]
        self.assertNotIn("私有用户消息", json.dumps(records, ensure_ascii=False))
        self.assertNotIn("Mikasa 回复", json.dumps(records, ensure_ascii=False))
        self.assertEqual(len(self.gateway.calls), 1)
        self.assertEqual(self.chat.get(self.session['id'], self.config.owner)['turns'][0]['message'], "私有用户消息")

    def test_cli_follows_new_session_id_and_closes_runtime(self):
        from mikasa.cli import main
        with patch("mikasa.chat.Chat", return_value=self.chat), patch("builtins.input", side_effect=["/reset", "新会话消息", "/exit"]), redirect_stdout(io.StringIO()):
            code = main(["--config", str(self.config_path), "chat", "--session", self.session["id"]])
        self.assertEqual(code, 0)
        self.assertTrue(self.gateways.closed)
        self.assertNotEqual(self.gateway.calls[-1]["session"], self.session["id"])
        self.assertEqual(self.gateway.calls[-1]["message"], "新会话消息")

    def test_switch_persists_in_native_session_only(self):
        self.send("记住蓝鲸", "before")
        self.assertEqual(self.send("切换为 model-b", "switch")["revision"], 1)
        reopened = Chat(self.config, self.gateways)
        self.send("代号是什么", "after", reopened)
        self.assertEqual(self.gateway.calls[-1]["model"], "model-b")
        self.assertEqual(reopened.get(self.session['id'], self.config.owner)['turns'][0]['message'], "记住蓝鲸")
        self.assertEqual(reopened.create(self.config.owner)["model"], "model-a")

    def test_failed_switch_keeps_model_and_sanitizes_diagnostic(self):
        self.gateway.fail = True
        result = self.send("切换为 nonexistent", "failed")
        self.assertEqual(result["kind"], "switch_failed")
        self.assertEqual(result["model"], "model-a")
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(self.send("切换为 nonexistent", "failed"), result)
        self.assertEqual(self.chat.current(self.session["id"], self.config.owner)["model"], "model-a")

    def test_native_run_reference_replays_without_new_inference(self):
        first = self.send("你好", "same")
        self.assertEqual(self.send("你好", "same"), first)
        self.assertEqual(len(self.gateway.calls), 1)
        with self.assertRaises(Conflict):
            self.send("另一条", "same")

    def test_lost_receipt_resubmits_same_native_idempotency_key(self):
        with patch.object(self.chat, 'save_receipt', side_effect=RuntimeError('crash')), self.assertRaises(RuntimeError):
            self.send('原生幂等', 'recover')
        self.send('原生幂等', 'recover')
        self.assertEqual(len(self.gateway.calls), 1)

    def test_authorization_precedes_opening_another_profile(self):
        with self.assertRaises(NotFound):
            self.chat.send(self.session["id"], "human", "切换为 model-b", "foreign")
        self.assertNotIn('human', self.gateways.instances)
        other = self.chat.create('human')
        self.assertIn(other['id'], self.gateways.for_actor('human').sessions)
        self.assertNotIn(other['id'], self.gateway.sessions)

    def test_pause_during_validation_preserves_old_model(self):
        self.gateway.before_wait = lambda: self.chat.store.pause(True, self.config.owner)
        with self.assertRaises(Conflict):
            self.send("切换为 model-b")
        self.assertEqual(self.chat.current(self.session['id'], self.config.owner)['model'], 'model-a')

    def test_transcript_pagination_does_not_truncate_inference(self):
        # Display pagination is native-owned and never rebuilt into the next request.
        for i in range(50):
            self.send(str(i), str(i))
        self.assertEqual(len(self.chat.get(self.session['id'], self.config.owner)['turns']), 50)
        self.assertEqual(len(self.gateway.sessions[self.session['id']]['messages']), 100)

    def test_legacy_receipt_replay_does_not_invoke_model(self):
        expected = {'chat_id': self.session['id'], 'kind': 'chat', 'reply': '旧回执'}
        with self.chat.store.connect() as db:
            db.execute('INSERT INTO chat_turns(chat_id,request_key,message,response,created) VALUES(?,?,?,?,0)',
                       (self.session['id'], 'old', '旧消息', json.dumps(expected)))
        self.assertEqual(self.send('旧消息', 'old'), expected)
        self.assertEqual(self.gateway.calls, [])

    def test_native_interim_and_final_messages_are_both_visible(self):
        self.gateway.sessions[self.session['id']]['messages'] = [
            {'role':'user','content':'检查记录'}, {'role':'assistant','content':'先核对。'},
            {'role':'assistant','content':'', 'tool_calls':[{'name':'memory'}]},
            {'role':'tool','content':'internal'}, {'role':'assistant','content':'核对完成。'}]
        result = self.chat.get(self.session['id'], self.config.owner)
        self.assertEqual(result['turns'][0]['response']['reply'], '先核对。\n\n核对完成。')

    def test_stop_bypasses_busy_lock_but_enforces_ownership(self):
        self.send('一个任务', 'active')
        with self.chat.store.connect() as db:
            db.execute("UPDATE chat_requests SET active_run='run_fixture' WHERE chat_id=?", (self.session['id'],))
        with patch.object(self.gateway, 'request', create=True, return_value={'status':'stopping'}) as request:
            with self.chat.locked(self.session['id']):
                response = self.chat.stop(self.session['id'], self.config.owner)
            self.assertTrue(response['stop_requested'])
            request.assert_called_once_with('POST','/v1/runs/run_fixture/stop',{})
            with self.assertRaises(NotFound):
                self.chat.stop(self.session['id'], 'human')

    def test_http_chat_auth_native_history_and_shutdown(self):
        with patch.dict(os.environ, {"MIKASA_OWNER_API_TOKEN": "o" * 32}), patch('mikasa.chat.NativeGateways', return_value=self.gateways):
            server = make_server(self.service, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request("POST", "/chats", "{}")
                response = conn.getresponse(); self.assertEqual(response.status, 403); response.read()
                headers = {"Authorization": "Bearer " + "o" * 32, "Idempotency-Key": "http-chat"}
                conn.request("POST", "/chats", "{}", headers)
                response = conn.getresponse(); self.assertEqual(response.status, 201)
                session = json.loads(response.read())
                conn.request("POST", f"/chats/{session['id']}/messages", json.dumps({"message": "你好"}), headers)
                response = conn.getresponse(); self.assertEqual(response.status, 200); response.read()
                conn.request("GET", f"/chats/{session['id']}", headers=headers)
                response = conn.getresponse()
                self.assertEqual(json.loads(response.read())["turns"][0]['message'], '你好')
                conn.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(3)
        self.assertTrue(self.gateways.closed)
