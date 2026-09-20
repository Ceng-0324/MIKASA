"""Conversation-local model selection; CCH owns provider routing and rewriting."""
import fcntl
import json
import re
import time
import uuid
from contextlib import contextmanager

from .errors import Conflict, MikasaError, NotFound
from .model_settings import default_model, model_choices, validate_model
from .model_errors import ModelFailure
from .store import Store
from .worker import Worker


# Only a complete direct user command can change state. Quoted text, questions,
# compound requests and model-generated text never execute a switch.
SWITCH = re.compile(
    r"(?:(?:Mikasa|三笠)[，,：:\s]*)?(?:请|帮我|请帮我)?\s*"
    r"(?:(?:把|将)(?:当前|这次|本次)?(?:聊天|会话)?(?:的)?模型)?\s*"
    r"(?:切换|换|改)(?:一下)?(?:模型)?(?:为|成|到|用)\s*(?:模型\s*)?"
    r"([A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199})(?:\s*模型)?[。！!\s]*", re.IGNORECASE)
STATUS = {"当前模型", "现在用的什么模型", "现在用的什么模型？", "你现在用什么模型", "你现在用什么模型？", "/model"}
MODELS = {"可用模型", "有哪些模型", "有哪些模型？", "/models"}
RESET = {"恢复默认模型", "切换为默认模型", "/model default"}
HELP = "输入 /model 完整模型ID 或说“切换为 完整模型ID”即可切换 GPT、Claude 等已接入模型；/model 查看当前模型和配置候选，/model default 恢复默认。切换仅影响当前聊天；工程任务仍使用运行配置。"


def command(message):
    text = message.strip()
    if text in STATUS:
        return "status", None
    if text in MODELS:
        return "models", None
    if text in RESET:
        return "reset", None
    match = SWITCH.fullmatch(text) or re.fullmatch(r"/model\s+([A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199})", text)
    if match:
        # Chinese sentence full-stop is not part of a model ID; ASCII dots can be.
        return "switch", validate_model(match.group(1))
    if re.match(r"^(?:(?:Mikasa|三笠)[，,：:\s]*)?(?:请|帮我|请帮我)?\s*(?:切换|换成|换为|把模型|将模型|/model\b)", text, re.I):
        return "help", None
    if re.match(r"^/[A-Za-z][A-Za-z0-9_-]*(?:\s|$)", text):
        return "unsupported_command", None
    return "chat", None


class Chat:
    def __init__(self, config, worker_factory=Worker):
        self.config = config
        self.store = Store(config.runtime)
        self.worker_factory = worker_factory

    def create(self, actor):
        self.config.authorize(actor)
        model = default_model(self.config)
        chat_id = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("INSERT INTO chats(id,actor,model,created) VALUES(?,?,?,?)", (chat_id, actor, model, time.time()))
        return self.get(chat_id, actor)

    def get(self, chat_id, actor):
        self.config.authorize(actor)
        if not isinstance(chat_id, str) or not re.fullmatch(r"[0-9a-f]{32}", chat_id):
            raise NotFound("聊天不存在")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM chats WHERE id=? AND actor=?", (chat_id, actor)).fetchone()
            if row is None:
                raise NotFound("聊天不存在或不属于当前账号")
            turns = db.execute("SELECT message,response FROM chat_turns WHERE chat_id=? ORDER BY seq DESC LIMIT 41", (chat_id,)).fetchall()
        return {**dict(row), "history_truncated": len(turns) > 40,
                "turns": [{"message": t["message"], "response": json.loads(t["response"])} for t in reversed(turns[:40])]}

    @contextmanager
    def locked(self, chat_id):
        directory = self.config.runtime / "chat-locks"
        directory.mkdir(exist_ok=True, mode=0o700)
        with (directory / (chat_id + ".lock")).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Conflict("当前聊天正在处理上一条消息，请稍后重试") from exc
            yield

    def send(self, chat_id, actor, message, key):
        self.get(chat_id, actor)  # Validate ownership and path before locking.
        if not isinstance(message, str) or not message.strip() or len(message) > 10000:
            raise MikasaError("消息需要 1–10000 字符")
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise MikasaError("聊天请求需要 1–200 字符的 Idempotency-Key")
        with self.locked(chat_id):
            current = self.get(chat_id, actor)
            with self.store.connect() as db:
                previous = db.execute("SELECT message,response FROM chat_turns WHERE chat_id=? AND request_key=?", (chat_id, key)).fetchone()
            if previous:
                if previous["message"] != message:
                    raise Conflict("幂等键已用于另一条消息")
                return json.loads(previous["response"])
            if self.store.paused():
                raise Conflict("运行已暂停")
            kind, target = command(message)
            model = current["model"]
            execution = None
            changed = False
            if kind == "reset":
                target = default_model(self.config)
            if kind in {"switch", "reset"}:
                if target == model:
                    reply = f"当前会话已经使用请求模型 {model}。"
                else:
                    try:
                        _, execution = self.infer(target, "请简短回复：模型连接验证完成。", [])
                        if self.store.paused():
                            raise MikasaError("验证期间运行已暂停")
                    except MikasaError as exc:
                        kind = "switch_failed"
                        reply = f"未能验证 {target}，当前会话仍使用 {model}。请检查模型 ID、CCH 权限和路由后重试。"
                        if isinstance(exc, ModelFailure):
                            reply = f"未能验证 {target}，当前会话仍使用 {model}。{exc}。"
                            execution = {"error_code": exc.code}
                    else:
                        model, changed = target, True
                        reply = f"当前聊天的请求模型已切换为 {model}，后续消息使用此模型；聊天记录已保留。"
                        observed = execution.get("reported_model")
                        if observed and observed != model:
                            reply += f" CCH 返回的模型标识为 {observed}；请求已成功，但不能确认底层就是 {model}。"
                        elif not observed:
                            reply += " 网关未提供可记录的模型标识，实际路由以 CCH 为准。"
            elif kind == "status":
                reply = f"当前聊天的请求模型是 {model}。实际上游由 CCH 路由，其他聊天与工程任务不受本会话选择影响。"
                if message.strip() == "/model":
                    reply += "\n" + self.model_menu()
            elif kind == "models":
                reply = f"当前请求模型：{model}。\n" + self.model_menu()
            elif kind == "help":
                reply = HELP
            elif kind == "unsupported_command":
                reply = "这个系统命令尚未接入 Mikasa，未执行任何操作。" + HELP
            else:
                result, execution = self.infer(model, message, current["turns"], current["history_truncated"])
                reply = result["summary"]
            response = {"chat_id": chat_id, "kind": kind, "reply": reply, "model": model,
                        "revision": current["revision"] + int(changed), "execution": execution}
            if kind == "models" or (kind == "status" and message.strip() == "/model"):
                response["model_options"] = model_choices(self.config.data.get("worker", {}))
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                paused = db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
                if paused and paused[0] == "true":
                    raise Conflict("运行已暂停，本条回复和模型变更未保存")
                if changed:
                    db.execute("UPDATE chats SET model=?,revision=revision+1 WHERE id=?", (model, chat_id))
                    self.store.event(db, None, "chat_model_switched", actor,
                                     {"chat_id": chat_id, "from": current["model"], "to": model,
                                      "reported_model": execution.get("reported_model"), "request_key": key})
                db.execute("INSERT INTO chat_turns(chat_id,request_key,message,response,created) VALUES(?,?,?,?,?)",
                           (chat_id, key, message, json.dumps(response, ensure_ascii=False), time.time()))
            return response

    def model_menu(self):
        choices = model_choices(self.config.data.get("worker", {}))
        lines = ["已配置候选（可用性以切换验证为准，不是 CCH 完整目录）："] if choices else []
        lines.extend("/model " + name for name in choices)
        lines.append(HELP)
        return "\n".join(lines)

    def infer(self, model, message, turns, history_truncated=False):
        # One worker per call: runtime evidence cannot race across HTTP threads.
        worker = self.worker_factory(self.config)
        history, used = [], len(message.encode())
        cap = self.config.data.get("worker", {}).get("max_context_bytes", 200000)
        if used > cap:
            raise MikasaError("消息超出配置的上下文上限")
        for turn in reversed(turns):
            pair = [{"role": "user", "content": turn["message"]},
                    {"role": "assistant", "content": turn["response"]["reply"]}]
            size = len(json.dumps(pair, ensure_ascii=False).encode())
            if used + size > cap:
                break
            history[0:0] = pair
            used += size
        task = {"payload": {"kind": "chat", "title": message,
                            "acceptance": "按当前 Mikasa 身份直接回复用户。聊天不执行仓库、审批或配置操作；模型选择以宿主 model_selection 为准，不根据自我介绍猜测模型。"}}
        result = worker.execute(task, {"history": history, "history_truncated": history_truncated or len(history) < 2 * len(turns),
                                       "model_selection": {"requested_model": model}}, self.store.paused, model=model)
        return result, worker.last_runtime or {}
