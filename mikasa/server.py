import hmac
import json
import os
import re
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


def make_server(settings, host=None, port=None):
    config = settings.data.get("server", {})
    tokens = [os.environ.get(v, "") for v in config.get("tokens", {}).values()]
    if not tokens or any(len(t) < 32 for t in tokens) or len(set(tokens)) != len(tokens):
        raise MikasaError("启动 API 前必须为每个账号配置不同的至少 32 字符 token")
    from .chat import Chat
    chat = Chat(settings)

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
                    return self.respond(200, {"status": "ok", "paused": chat.store.paused()})
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
                if path == '/webhooks/github':
                    return self.respond(410, {'error': '工程 webhook 已退休；使用 engineer 原生入口。旧数据保留。'})
                actor = authenticate(settings, self.headers.get("Authorization", ""))
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
                if path == '/tasks' or path.startswith('/tasks/'):
                    return self.respond(410, {'error': '旧任务 API 已退休；使用 engineer -- kanban。旧看板为只读档案，不自动重跑。'})
                if path == "/control" and method == "POST":
                    settings.authorize(actor, owner=True)
                    if type(data.get("paused")) is not bool:
                        raise MikasaError("paused 必须为布尔值")
                    chat.store.pause(data["paused"], actor)
                    return self.respond(200, {"paused": data["paused"]})
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
