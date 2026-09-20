import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import Conflict, Forbidden, MikasaError, NotFound

MAX_BODY = 1_000_000


def authenticate(config, header):
    if not header.startswith("Bearer "):
        raise Forbidden("需要 Bearer token")
    supplied = header[7:]
    for actor, variable in config.data.get("server", {}).get("tokens", {}).items():
        expected = os.environ.get(variable, "")
        if expected and hmac.compare_digest(supplied.encode(), expected.encode()):
            config.authorize(actor)
            return actor
    raise Forbidden("身份验证失败")


def webhook(service, headers, raw):
    secret = service.config.secret("server", "webhook_secret_env", "MIKASA_GITHUB_WEBHOOK_SECRET")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    signature = headers.get("X-Hub-Signature-256", "")
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        raise Forbidden("webhook 签名无效")
    delivery = headers.get("X-GitHub-Delivery", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", delivery):
        raise MikasaError("缺少合法 delivery ID")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise MikasaError("webhook body 必须为对象")
    event = headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"pong": True}
    repo = payload.get("repository", {}).get("full_name")
    service.config.repo(repo)
    # Keep only metadata; external text cannot change policy or dispatch implementation.
    summary = {"event": event, "action": payload.get("action"), "repo": repo, "number": payload.get("number"),
               "sender": payload.get("sender", {}).get("login"),
               "head": payload.get("pull_request", {}).get("head", {}).get("sha")}
    if (service.config.data.get("server", {}).get("auto_review") is True and event == "pull_request"
            and payload.get("action") in {"opened", "reopened", "synchronize", "ready_for_review"}):
        service.submit({"kind": "review", "repo": repo, "pr": payload["number"],
                        "title": f"审查 PR #{payload['number']}", "acceptance": "依据当前版本形成审查草稿、验证证据和限制"},
                       service.config.owner, f"github:{delivery}")
    return {"accepted": True, "duplicate": not service.store.delivery(delivery, summary)}


def make_server(service, host=None, port=None):
    config = service.config.data.get("server", {})
    tokens = [os.environ.get(v, "") for v in config.get("tokens", {}).values()]
    if not tokens or any(len(t) < 32 for t in tokens) or len(set(tokens)) != len(tokens):
        raise MikasaError("启动 API 前必须为每个账号配置不同的至少 32 字符 token")
    from .chat import Chat
    chat = Chat(service.config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Mikasa"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format, *args):
            pass  # Never log request headers, query tokens, or user payloads.

        def respond(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def handle_request(self, method):
            try:
                path = self.path
                if method == "GET" and path == "/health":
                    return self.respond(200, {"status": "ok", "paused": service.store.paused()})
                if method == "GET" and path == "/chat":
                    page = Path(__file__).with_name("chat.html").read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                    self.end_headers()
                    self.wfile.write(page)
                    return
                raw = b""
                if method == "POST":
                    if self.headers.get("Transfer-Encoding"):
                        raise MikasaError("不支持流式请求体")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_BODY:
                        raise MikasaError("请求体为空或超出大小限制")
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise MikasaError("请求体不完整")
                if method == "POST" and path == "/webhooks/github":
                    return self.respond(200, webhook(service, self.headers, raw))
                actor = authenticate(service.config, self.headers.get("Authorization", ""))
                data = json.loads(raw) if raw else {}
                if not isinstance(data, dict):
                    raise MikasaError("body 必须为对象")
                if path == "/chats" and method == "POST":
                    if data:
                        raise MikasaError("创建聊天不接受身份或模型覆盖字段")
                    return self.respond(201, chat.create(actor))
                chat_match = re.fullmatch(r"/chats/([0-9a-f]{32})(/messages|/stop)?", path)
                if chat_match:
                    chat_id, messages = chat_match.groups()
                    if method == "GET" and messages is None:
                        return self.respond(200, chat.get(chat_id, actor))
                    if method == "POST" and messages == "/stop":
                        if data:
                            raise MikasaError("停止请求不接受参数")
                        return self.respond(200, chat.stop(chat_id, actor))
                    if method == "POST" and messages:
                        if set(data) != {"message"}:
                            raise MikasaError("聊天请求只接受 message")
                        return self.respond(200, chat.send(chat_id, actor, data["message"], self.headers.get("Idempotency-Key", "")))
                if path == "/tasks" and method == "GET":
                    return self.respond(200, service.store.list())
                if path == "/tasks" and method == "POST":
                    return self.respond(201, service.submit(data, actor, self.headers.get("Idempotency-Key", "")))
                if path == "/control" and method == "POST":
                    service.config.authorize(actor, owner=True)
                    if type(data.get("paused")) is not bool:
                        raise MikasaError("paused 必须为布尔值")
                    service.store.pause(data["paused"], actor)
                    return self.respond(200, {"paused": data["paused"]})
                if path == "/provenance" and method == "POST":
                    return self.respond(200, service.record_provenance(data["repo"], data["pr"], data["head"], data["provenance"], actor))
                match = re.fullmatch(r"/tasks/([0-9a-f]{32})(?:/(events|cancel|retry|assign|complete|expand|publish|reconcile))?", path)
                if match:
                    task, action = match.groups()
                    if method == "GET" and action in {None, "events"}:
                        return self.respond(200, service.store.events(task) if action else service.store.get(task))
                    if method == "POST" and action:
                        if action == "expand":
                            value = service.expand(task, actor)
                        elif action == "publish":
                            value = service.publish(task, actor)
                        elif action == "reconcile":
                            value = service.reconcile(task, data["pr"], actor)
                        elif action in {"cancel", "retry", "assign", "complete"}:
                            value = service.action(task, action, actor, data)
                        else:
                            raise NotFound("路由不存在")
                        return self.respond(200, value)
                raise NotFound("路由不存在")
            except Forbidden as exc:
                self.respond(403, {"error": str(exc)})
            except NotFound as exc:
                self.respond(404, {"error": str(exc)})
            except Conflict as exc:
                self.respond(409, {"error": str(exc)})
            except (MikasaError, ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": str(exc) if isinstance(exc, MikasaError) else "请求格式不正确"})
            except Exception:
                self.respond(500, {"error": "内部处理失败；请检查运行环境"})

        def do_GET(self):
            self.handle_request("GET")

        def do_POST(self):
            self.handle_request("POST")

    class Server(ThreadingHTTPServer):
        def server_close(self):
            super().server_close()
            chat.close()

    server = Server((host if host is not None else config.get("host", "127.0.0.1"),
                                 port if port is not None else config.get("port", 8765)), Handler)
    server.daemon_threads = True
    return server
