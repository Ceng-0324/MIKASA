"""Task-scoped Hermes tools. The host owns access, execution and evidence."""
import hashlib
import json
import socket
import threading
import uuid
from pathlib import PurePosixPath

from .errors import MikasaError
from .process import check_command, git
from .workspace import PROTECTED, sensitive

LIMIT = 1_100_000
FILE_LIMIT = 1_000_000
READ_CHARS = 16000


def schema(name, description, properties, required=()):
    return {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(required), "additionalProperties": False}}


READ_TOOLS = [
    schema("mikasa_list_files", "List repository paths, with pagination. Secrets are excluded; symlink contents cannot be read.", {"offset": {"type": "integer", "minimum": 0}}),
    schema("mikasa_read_file", "Read a text file page. Follow next_offset until null for complete coverage; offsets count Unicode characters. Review reads pinned PR head.", {"path": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}}, ["path"]),
    schema("mikasa_search", "Search literal text. Repeat the same query with next_cursor until null; skipped files remain uncovered.", {"query": {"type": "string"}, "cursor": {"type": "string"}}, ["query"]),
]
WRITE_TOOLS = [
    schema("mikasa_apply_changes", "Apply and stage complete file contents. Rules, credentials and execution configuration are protected.", {
        "changes": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": ["string", "null"]}}, "required": ["path", "content"], "additionalProperties": False}}}, ["changes"]),
    schema("mikasa_run_checks", "Run ONLY host-configured checks. Observe failures, repair, then recheck. Cannot supply commands.", {}),
]


def run_checks(workspace, cancelled):
    evidence = []

    def checked_git(args):
        return git(args, workspace.path, cancelled=cancelled)

    index = checked_git(["write-tree"])
    for command in workspace.spec.get("checks", []):
        if cancelled():
            raise MikasaError("任务已取消或运行已暂停")
        check = check_command(command, workspace.spec, workspace.path,
                              workspace.config.data.get("worker", {}).get("timeout", 600), cancelled)
        evidence.append({"command": command, **check})
        if checked_git(["write-tree"]) != index or checked_git(["rev-parse", "HEAD"]) != workspace.base:
            raise MikasaError("验证命令修改了 Git 索引或提交；拒绝交付")
        if checked_git(["diff", "--name-only"]):
            raise MikasaError("验证命令修改了已暂存内容；拒绝提交未经验证的版本")
        if check["code"]:
            break
    return evidence


class ToolSession:
    def __init__(self, workspace, kind, cancelled):
        self.workspace, self.kind = workspace, kind
        self.cancelled = cancelled
        self.stopped = threading.Event()
        self.schemas = READ_TOOLS + (WRITE_TOOLS if kind == "implement" else []) if workspace else []
        self.events = []
        self.coverage = {}
        self.cursors = {}
        self.applied = False
        self.fatal = None
        self.parent = self.child = self.thread = None

    def __enter__(self):
        if self.schemas:
            self.parent, self.child = socket.socketpair()
            self.thread = threading.Thread(target=self.serve, name="mikasa-tools", daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        if self.parent:
            try:
                self.parent.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.child.close()
            self.thread.join()
            self.parent.close()

    def is_cancelled(self):
        return self.stopped.is_set() or self.cancelled()

    def serve(self):
        try:
            with self.parent.makefile("rwb") as stream:
                while not self.is_cancelled():
                    line = stream.readline(LIMIT + 1)
                    if not line or len(line) > LIMIT:
                        break
                    try:
                        request = json.loads(line)
                        result = self.call(request["name"], request["arguments"])
                    except (ValueError, KeyError, TypeError):
                        result = {"error": "非法工具请求"}
                    encoded = json.dumps(result, ensure_ascii=False).encode()
                    if len(encoded) > LIMIT:
                        encoded = b'{"error":"tool output exceeded limit"}'
                    stream.write(encoded + b"\n")
                    stream.flush()
        except (OSError, ValueError):
            pass
        except Exception:
            self.fatal = "宿主工具通道异常；拒绝交付"
            self.parent.shutdown(socket.SHUT_RDWR)

    def git(self, args, *, strip=True, decode_errors="replace"):
        return git(args, self.workspace.path, strip=strip, cancelled=self.is_cancelled, decode_errors=decode_errors)

    def files(self):
        w = self.workspace
        if self.kind == "implement":
            names = self.git(["ls-files", "-z"], strip=False).split("\0")
        else:
            names = self.git(["ls-tree", "-r", "--name-only", "-z", w.head], strip=False).split("\0")
        return sorted(n for n in names if n and not sensitive(n) and not set(PurePosixPath(n).parts) & PROTECTED)

    def read(self, name, names=None):
        w = self.workspace
        if not isinstance(name, str) or name not in (self.files() if names is None else names):
            raise MikasaError("路径不在可读仓库文件中")
        if self.kind == "implement":
            target = w.path / name
            if any(p.is_symlink() for p in [target, *target.parents]) or not target.is_file() or target.stat().st_size > FILE_LIMIT:
                raise MikasaError("文件为链接、非普通文件或超过 1000000 字节")
            with target.open("rb") as source:
                raw = source.read(FILE_LIMIT + 1)
            if len(raw) > FILE_LIMIT:
                raise MikasaError("文件超过 1000000 字节")
            content = raw.decode("utf-8")
        else:
            entry = self.git(["ls-tree", w.head, "--", name])
            if not entry.startswith(("100644 ", "100755 ")) or int(self.git(["cat-file", "-s", f"{w.head}:{name}"])) > FILE_LIMIT:
                raise MikasaError("文件为链接、非普通文件或超过 1000000 字节")
            content = self.git(["show", f"{w.head}:{name}"], strip=False, decode_errors="strict")
        if "\x00" in content:
            raise MikasaError("不读取二进制文件")
        return content

    def read_page(self, args):
        offset = args.get("offset", 0)
        if type(offset) is not int or offset < 0:
            raise MikasaError("非法 offset")
        content = self.read(args["path"])
        if offset > len(content):
            raise MikasaError("offset 超出文件长度")
        sha = hashlib.sha256(content.encode()).hexdigest()
        end = min(offset + READ_CHARS, len(content))
        key = (args["path"], sha)
        ranges = sorted(self.coverage.get(key, []) + [(offset, end)])
        covered = 0
        for start, stop in ranges:
            if start > covered:
                break
            covered = max(covered, stop)
        self.coverage[key] = ranges
        return {"path": args["path"], "content": content[offset:end], "offset": offset,
                "next_offset": end if end < len(content) else None, "total_chars": len(content),
                "sha256": sha, "complete": covered == len(content),
                "revision": self.workspace.head if self.kind != "implement" else "working_tree"}

    def search_page(self, args):
        query = args["query"]
        if not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise MikasaError("query 需要 1–200 字符")
        names = self.files()
        names_sha = hashlib.sha256("\0".join(names).encode()).hexdigest()
        tree = self.git(["write-tree"]) if self.kind == "implement" else self.workspace.head
        index, line_offset, previous_sha = 0, 0, None
        cursor = args.get("cursor")
        if cursor is not None:
            if not isinstance(cursor, str) or cursor not in self.cursors:
                raise MikasaError("搜索 cursor 无效；从头重新搜索")
            state = self.cursors[cursor]
            if state["query"] != query or state["tree"] != tree or state["names_sha"] != names_sha:
                raise MikasaError("搜索条件或仓库已变化；从头重新搜索")
            index, line_offset, previous_sha = state["index"], state["line"], state["sha"]
        matches, skipped, scanned, used = [], [], 0, 0
        while index < len(names) and scanned < 100 and used < FILE_LIMIT:
            if self.is_cancelled():
                raise MikasaError("任务已取消")
            path = names[index]
            scanned += 1
            try:
                content = self.read(path, names)
            except (MikasaError, UnicodeError):
                skipped.append(path)
                index, line_offset, previous_sha = index + 1, 0, None
                continue
            sha = hashlib.sha256(content.encode()).hexdigest()
            if previous_sha is not None and previous_sha != sha:
                raise MikasaError("搜索文件已变化；从头重新搜索")
            lines = content.splitlines()
            used += len(content.encode())
            while line_offset < len(lines):
                line = lines[line_offset]
                line_offset += 1
                if query in line:
                    matches.append({"path": path, "line": line_offset, "text": line[:300]})
                    if len(matches) == 100:
                        break
            if line_offset == len(lines):
                index, line_offset, previous_sha = index + 1, 0, None
            else:
                previous_sha = sha
            if len(matches) == 100:
                break
        next_cursor = None
        if index < len(names):
            next_cursor = uuid.uuid4().hex
            self.cursors[next_cursor] = {"query": query, "tree": tree, "names_sha": names_sha,
                                         "index": index, "line": line_offset, "sha": previous_sha}
        return {"matches": matches, "skipped": skipped, "scanned_files": scanned,
                "truncated": next_cursor is not None, "next_cursor": next_cursor}

    def call(self, name, args):
        event = {"tool": name, "ok": False}
        try:
            if len(self.events) >= 64 or self.is_cancelled() or self.fatal:
                raise MikasaError("工具预算耗尽、取消或检查完整性失败")
            definition = next((s for s in self.schemas if s["name"] == name), None)
            if not definition or not isinstance(args, dict):
                raise MikasaError("工具未授权")
            params = definition["parameters"]
            if set(args) - set(params["properties"]) or set(params["required"]) - set(args):
                raise MikasaError("工具参数不符合契约")
            if name == "mikasa_list_files":
                offset = args.get("offset", 0)
                if type(offset) is not int or offset < 0:
                    raise MikasaError("非法 offset")
                names = self.files()
                result = {"files": names[offset:offset + 200], "total": len(names), "next_offset": offset + 200 if offset + 200 < len(names) else None}
            elif name == "mikasa_read_file":
                result = self.read_page(args)
                event.update({k: result[k] for k in ("path", "revision", "sha256", "offset", "next_offset", "total_chars", "complete")})
            elif name == "mikasa_search":
                result = self.search_page(args)
                event.update({"continued": "cursor" in args, "truncated": result["truncated"],
                              "matches": len(result["matches"]), "skipped": result["skipped"]})
            elif name == "mikasa_apply_changes":
                self.workspace.apply(args["changes"], cancelled=self.is_cancelled)
                self.applied = True
                self.coverage.clear()
                self.cursors.clear()
                result = {"applied": [c["path"] for c in args["changes"]]}
                event["paths"] = result["applied"]
            else:
                try:
                    checks = run_checks(self.workspace, self.is_cancelled)
                except MikasaError:
                    self.fatal = "工具检查执行失败或破坏验证完整性；拒绝交付"
                    raise
                result = {"checks": checks, "passed": bool(checks) and all(c["code"] == 0 for c in checks)}
                event["checks"] = [{"command": c["command"], "code": c["code"]} for c in checks]
            event["ok"] = True
            return result
        except (MikasaError, OSError, UnicodeError) as exc:
            return {"error": str(exc) if isinstance(exc, MikasaError) else "文件读取失败"}
        finally:
            if len(self.events) < 65:
                self.events.append(event)
