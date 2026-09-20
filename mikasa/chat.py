"""Conversation-local model selection; CCH owns provider routing and rewriting."""
import hashlib
import fcntl
import json
import re
import time
import uuid
from contextlib import contextmanager

from .errors import Conflict, MikasaError, NotFound
from .model_settings import default_model, model_choices
from .store import Store
from .worker import Worker
from .native import NativeAPIError, NativeGateways


# Only a complete direct user command can change state. Quoted text, questions,
# compound requests and model-generated text never execute a switch.
SWITCH = re.compile(
    r"(?:(?:Mikasa|三笠)[，,：:\s]*)?(?:请|帮我|请帮我)?\s*"
    r"(?:(?:把|将)(?:当前|这次|本次)?(?:聊天|会话)?(?:的)?模型)?\s*"
    r"(?:切换|换|改)(?:一下)?(?:模型)?(?:为|成|到|用)\s*(?:模型\s*)?"
    r"([A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199})(?:\s*模型)?[。！!\s]*", re.IGNORECASE)
STATUS = {"当前模型", "现在用的什么模型", "现在用的什么模型？", "你现在用什么模型", "你现在用什么模型？"}
MODELS = {"可用模型", "有哪些模型", "有哪些模型？", "/models"}
RESET = {"恢复默认模型", "切换为默认模型"}
HELP = "输入 /model 完整模型ID 或说“切换为 完整模型ID”即可切换 GPT、Claude 等已接入模型；/model 查看当前模型和配置候选，/model default 恢复默认。/new（或 /reset）新建聊天并保留当前模型，旧记录可恢复；/version 查看 Hermes 版本，/help 查看帮助。切换仅影响当前聊天；工程任务仍使用运行配置。"


def command(message, resolve):
    text = message.strip()
    if text in STATUS:
        text = "/model"
    if text in MODELS:
        text = "/model"
    if text in RESET:
        text = "/model default"
    match = SWITCH.fullmatch(text)
    if match:
        text = "/model " + match.group(1)
    if text.startswith("/"):
        return resolve(text)
    if re.match(r"^(?:(?:Mikasa|三笠)[，,：:\s]*)?(?:请|帮我|请帮我)?\s*(?:切换|换成|换为|把模型|将模型)", text, re.I):
        return {"kind": "help", "target": None, "reply": None, "name": None}
    return {"kind": "chat", "target": None, "reply": None, "name": None}


class Chat:
    """Business authorization and command receipts; Hermes owns conversation state."""
    def __init__(self, config, native_gateways=None):
        self.config = config
        self.store = Store(config.runtime)
        self.gateways = native_gateways or NativeGateways(config)

    def close(self):
        self.gateways.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def create(self, actor):
        self.config.authorize(actor)
        session = uuid.uuid4().hex
        self.gateways.for_actor(actor).ensure_session(session, default_model(self.config))
        self.bind(session, actor)
        return self.get(session, actor)

    def bind(self, session, actor):
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO chat_links(id,actor,created) VALUES(?,?,?)", (session, actor, time.time()))

    def owned(self, session, actor):
        self.config.authorize(actor)
        if not isinstance(session, str) or not re.fullmatch(r"[0-9a-f]{32}", session):
            raise NotFound("聊天不存在")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM chat_links WHERE id=? AND actor=?", (session, actor)).fetchone()
            legacy = db.execute("SELECT * FROM chats WHERE id=? AND actor=?", (session, actor)).fetchone() if row is None else None
        if row is None and legacy is None:
            raise NotFound("聊天不存在或不属于当前账号")
        # Gateway startup imports the actor's legacy transcripts before accepting requests.
        if row is None:
            self.gateways.for_actor(actor)
            self.bind(session, actor)
            return self.owned(session, actor)
        return dict(row)

    def current(self, session, actor):
        owned = self.owned(session, actor)
        gateway = self.gateways.for_actor(actor)
        native = gateway.session(session)
        return {**owned, "model": native["model"]}

    def get(self, session, actor):
        current = self.current(session, actor)
        native = self.gateways.for_actor(actor).messages(session)
        turns, pending = [], None
        # Native "latest" chooses a tail page, but returns it in chronological order.
        for item in native["data"]:
            if item.get("role") == "user":
                pending = {"message": item.get("content", ""), "response": {"kind": "chat", "reply": ""}}
                turns.append(pending)
            elif item.get("role") == "assistant" and item.get("content") and not item.get("tool_calls") and pending is not None:
                previous = pending["response"]["reply"]
                pending["response"]["reply"] = previous + ("\n\n" if previous else "") + item["content"]
        return {**current, "native_session_id": native["session_id"], "turns": turns,
                "history_truncated": len(native["data"]) >= native["pagination"]["limit"]}

    @contextmanager
    def locked(self, session):
        directory = self.config.runtime / "chat-locks"
        directory.mkdir(exist_ok=True, mode=0o700)
        with (directory / (session + ".lock")).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Conflict("当前聊天正在处理上一条消息，请稍后重试") from exc
            yield

    def replay(self, receipt, gateway):
        response = json.loads(receipt)
        if "run_id" in response:
            status = gateway.wait(response["run_id"], self.store.paused)
            with self.store.connect() as db:
                db.execute("UPDATE chat_requests SET active_run=NULL WHERE active_run=?", (response["run_id"],))
            response["reply"] = status.get("output", "")
            response["execution"] = {"backend": "hermes-gateway", "run_id": response.pop("run_id"),
                                     **status.get("runtime", {})}
        return response

    def track_run(self, session, key, run):
        with self.store.connect() as db:
            db.execute("UPDATE chat_requests SET active_run=? WHERE chat_id=? AND request_key=?", (run, session, key))

    def stop(self, session, actor):
        self.owned(session, actor)
        gateway = self.gateways.for_actor(actor)
        with self.store.connect() as db:
            runs = [r[0] for r in db.execute("SELECT active_run FROM chat_requests WHERE chat_id=? AND active_run IS NOT NULL", (session,))]
        stopped = []
        for run in runs:
            try:
                status = gateway.request("POST", "/v1/runs/" + run + "/stop", {})
            except NativeAPIError as exc:
                if exc.status != 404:
                    raise
                status = {"status": "expired"}
            if status["status"] == "stopping":
                stopped.append(run)
            else:
                with self.store.connect() as db:
                    db.execute("UPDATE chat_requests SET active_run=NULL WHERE chat_id=? AND active_run=?", (session, run))
        return {"chat_id": session, "stop_requested": bool(stopped), "runs": stopped}

    def send(self, session, actor, message, key):
        self.owned(session, actor)  # Authenticate before opening an actor's native profile.
        if not isinstance(message, str) or not message.strip() or len(message) > 10000:
            raise MikasaError("消息需要 1–10000 字符")
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise MikasaError("聊天请求需要 1–200 字符的 Idempotency-Key")
        digest = hashlib.sha256(message.encode()).hexdigest()
        native_key = hashlib.sha256((session + "\0" + key).encode()).hexdigest()
        with self.locked(session):
            gateway = self.gateways.for_actor(actor)
            with self.store.connect() as db:
                previous = db.execute("SELECT * FROM chat_requests WHERE chat_id=? AND request_key=?", (session, key)).fetchone()
                legacy = db.execute("SELECT message,response FROM chat_turns WHERE chat_id=? AND request_key=?", (session, key)).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise Conflict("幂等键已用于另一条消息")
                if previous["receipt"]:
                    return self.replay(previous["receipt"], gateway)
            elif legacy:
                if legacy["message"] != message:
                    raise Conflict("幂等键已用于另一条消息")
                return json.loads(legacy["response"])
            if self.store.paused():
                raise Conflict("运行已暂停")
            parsed = command(message, lambda text: Worker(self.config).command(text, self.store.paused))
            if self.store.paused():
                raise Conflict("运行已暂停")
            current = self.current(session, actor)
            kind, target, model = parsed["kind"], parsed["target"], current["model"]
            if previous and previous["kind"] != kind:
                raise Conflict("未完成请求的命令语义已变化；请核对后使用新的幂等键")
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO chat_requests(chat_id,request_key,digest,kind,request_model,request_revision) VALUES(?,?,?,?,?,?)",
                           (session, key, digest, kind, model, current["revision"]))
            if previous and kind == "chat" and previous["request_model"]:
                model = previous["request_model"]
                current["revision"] = previous["request_revision"]
            response = {"chat_id": session, "kind": kind, "model": model, "revision": current["revision"], "execution": None}
            if kind == "chat":
                run = gateway.start(session, message, model, native_key)
                self.track_run(session, key, run["run_id"])
                response["run_id"] = run["run_id"]
                # Store only the native run reference, never another copy of the transcript.
                self.save_receipt(session, key, response)
                return self.replay(json.dumps(response), gateway)
            if kind == "reset":
                target = default_model(self.config)
            if kind in {"switch", "reset"}:
                if target != model:
                    probe = uuid.uuid5(uuid.NAMESPACE_URL, "mikasa-probe:" + native_key).hex
                    gateway.ensure_session(probe, target)
                    try:
                        run = gateway.start(probe, "请简短回复：模型连接验证完成。", target, "probe-" + native_key)
                        self.track_run(session, key, run["run_id"])
                        completed = gateway.wait(run["run_id"], self.store.paused)
                    except MikasaError:
                        if self.store.paused():
                            raise Conflict("运行已暂停") from None
                        response.update(kind="switch_failed", reply=f"未能验证 {target}，当前聊天仍使用 {model}。请检查 CCH 模型 ID、权限及路由。")
                    else:
                        if self.store.paused():
                            raise Conflict("验证期间运行已暂停，模型未切换")
                        gateway.set_model(session, target)
                        response.update(model=target, revision=current["revision"] + 1,
                                        execution={"backend": "hermes-gateway", **completed.get("runtime", {})},
                                        reply=f"当前聊天已切换请求模型为 {target}，原生历史保留。实际供应商和分组以 CCH 为准。")
                else:
                    response["reply"] = f"当前聊天已经使用请求模型 {model}。"
            elif kind == "new":
                next_id = uuid.uuid5(uuid.NAMESPACE_URL, "mikasa-new:" + native_key).hex
                gateway.ensure_session(next_id, model)
                self.bind(next_id, actor)
                response.update(chat_id=next_id, revision=0, reply=f"已开始新聊天 {next_id}，继续使用 {model}；旧聊天 {session} 可恢复，账号长期记忆保留。")
            elif kind == "status":
                response.update(reply=f"当前聊天的请求模型是 {model}。\n" + self.model_menu(),
                                model_options=model_choices(self.config.data.get("worker", {})))
            elif kind == "help":
                response["reply"] = (parsed["reply"] + "\n" if parsed["reply"] else "") + HELP
            elif kind in {"version", "deferred_command"}:
                response["reply"] = parsed["reply"]
            else:
                response["reply"] = "这个系统命令尚未接入 Mikasa，未执行操作。" + HELP
            self.save_receipt(session, key, response)
            return response

    def save_receipt(self, session, key, response):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE chat_requests SET receipt=? WHERE chat_id=? AND request_key=?", (json.dumps(response, ensure_ascii=False), session, key))
            if response["kind"] != "chat":
                db.execute("UPDATE chat_requests SET active_run=NULL WHERE chat_id=? AND request_key=?", (session, key))
            if response["kind"] in {"switch", "reset"} and response["model"]:
                db.execute("UPDATE chat_links SET revision=? WHERE id=?", (response["revision"], session))
            self.store.event(db, None, "chat_" + response["kind"], "runtime", {"chat_id": session, "request_key": key})

    def model_menu(self):
        choices = model_choices(self.config.data.get("worker", {}))
        return "已配置候选（可用性以切换验证为准，不是 CCH 完整目录）：\n" + "\n".join("/model " + name for name in choices) + "\n" + HELP
