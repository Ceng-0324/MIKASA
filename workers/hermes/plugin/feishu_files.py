"""On-demand Feishu reads through Hermes' live adapter and native tool registry.

The official lark-mcp currently excludes binary downloads. Retire these tools
when upstream supplies chat lookup and native local-file download equivalents.
No background history collection, credential copy, or separate agent runtime.
"""
import asyncio
import json
import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)


class PlatformReadError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Feishu API failed: code={code}")


def _items(response):
    if not response or not response.success():
        raise PlatformReadError(getattr(response, "code", "unknown"))
    return getattr(getattr(response, "data", None), "items", None) or []


def _incoming(item):
    return SimpleNamespace(message_id=item.message_id, message_type=item.msg_type,
                           content=getattr(item.body, "content", ""), mentions=getattr(item, "mentions", None))


def _describe(adapter, item):
    incoming = _incoming(item)
    normalized = adapter._normalize(incoming.message_type, incoming.content, incoming.mentions)
    attachments = [{"kind": ref.resource_type, "name": ref.file_name} for ref in normalized.media_refs]
    attachments.extend({"kind": "image"} for _ in normalized.image_keys)
    if item.msg_type == "folder":
        attachments.append({"kind": "folder", "download_supported": False})
    text = normalized.text_content or normalized.metadata.get("placeholder_text") or ""
    return {"message_id": item.message_id, "chat_id": item.chat_id,
            "thread_id": getattr(item, "thread_id", None), "parent_id": getattr(item, "parent_id", None),
            "type": item.msg_type, "sender_id": getattr(getattr(item, "sender", None), "id", None),
            "create_time": getattr(item, "create_time", None), "deleted": bool(getattr(item, "deleted", False)),
            "text": text[:2000], "text_truncated": len(text) > 2000, "attachments": attachments}


async def _message(adapter, message_id, chat_id):
    if not message_id:
        raise ValueError("message_id is required; use feishu_messages to find it")
    response = await adapter._run_blocking(adapter._client.im.v1.message.get,
                                           adapter._build_get_message_request(message_id))
    item = next((m for m in _items(response) if m.message_id == message_id), None)
    if item is None or getattr(item, "deleted", False):
        raise ValueError("Message is missing or deleted")
    if chat_id and item.chat_id != chat_id:
        raise ValueError("Message belongs to a different chat than the requested chat_id")
    return item


async def _read(adapter, args, chat_id):
    from lark_oapi.api.im.v1 import ListMessageRequest
    action = args.get("action", "list")
    if action == "get":
        item = await _message(adapter, args.get("message_id"), chat_id)
        return {"items": [_describe(adapter, item)], "has_more": False}
    if action != "list":
        raise ValueError("action must be list or get")
    thread = args.get("thread_id")
    if not chat_id and not thread:
        raise ValueError("Provide chat_id (or thread_id) outside a Feishu conversation")
    page_size = args.get("page_size", 30)
    if type(page_size) is not int or not 1 <= page_size <= 50:
        raise ValueError("page_size must be an integer from 1 to 50")
    if thread and (args.get("start_time") or args.get("end_time")):
        raise ValueError("Feishu thread queries do not support start_time/end_time")
    builder = (ListMessageRequest.builder().container_id_type("thread" if thread else "chat")
               .container_id(thread or chat_id).page_size(page_size).sort_type("ByCreateTimeDesc"))
    for key in ("start_time", "end_time", "page_token"):
        if args.get(key):
            builder = getattr(builder, key)(args[key])
    response = await adapter._run_blocking(adapter._client.im.v1.message.list, builder.build())
    items = _items(response)
    query = str(args.get("query") or "").casefold()
    found = []
    for item in items:
        if getattr(item, "deleted", False) or (chat_id and item.chat_id != chat_id):
            continue
        described = _describe(adapter, item)
        if args.get("attachments_only", False) and not described["attachments"]:
            continue
        # Match the full body before truncating the returned preview. A query
        # filters this API page only; expose its cursor even when no item matches.
        body = json.dumps(json.loads(item.body.content), ensure_ascii=False)
        if query and query not in body.casefold():
            continue
        found.append(described)
    return {"items": found, "scanned": len(items), "has_more": bool(response.data.has_more),
            "page_token": response.data.page_token,
            "note": "Filters apply to this page only. Continue with page_token and the same filters when has_more=true."}


async def _download(adapter, args, chat_id):
    item = await _message(adapter, args.get("message_id"), chat_id)
    described = _describe(adapter, item)
    if item.msg_type == "folder":
        return {"status": "unsupported", "message": described, "files": [],
                "reason": "Feishu only supports chat-folder downloads in its client, not OpenAPI. Ask for a ZIP or accessible repository."}
    incoming = _incoming(item)
    normalized = adapter._normalize(incoming.message_type, incoming.content, incoming.mentions)
    expected = len(normalized.media_refs) + len(normalized.image_keys)
    if not expected:
        return {"status": "no_attachment", "message": described, "files": []}
    # Native download/cache owns names, file types and storage. Never return
    # binary data or extract archives here; Hermes' ordinary tools do the work.
    _, _, paths, types, _, _ = await adapter._extract_message_content(incoming)
    files = [{"path": path, "mime_type": kind} for path, kind in zip(paths, types)]
    status = "downloaded" if len(paths) == expected else "partial" if paths else "failed"
    return {"status": status, "message": described, "files": files, "expected_files": expected,
            "note": "Read the returned local paths using native file/terminal tools. Missing files were not read; check resource permissions/availability and native file-size limits."}


async def _handle(operation, args):
    from gateway.config import Platform
    from gateway.session_context import get_session_env
    from tools.registry import tool_error, tool_result
    from tools.send_message_senders import _live_adapter
    runner, adapter = _live_adapter(Platform.FEISHU)
    if adapter is None or adapter._client is None:
        return tool_error("No live Feishu adapter for this Hermes profile; run the connected messaging Gateway.")
    current_chat = (get_session_env("HERMES_SESSION_CHAT_ID", "")
                    if get_session_env("HERMES_SESSION_PLATFORM", "") == "feishu" else "")
    chat_id = args.get("chat_id") or current_chat
    try:
        loop = getattr(runner, "_gateway_loop", None)
        if loop is not None and loop is not asyncio.get_running_loop():
            if not loop.is_running():
                raise ValueError("Feishu Gateway loop is not running")
            from agent.async_utils import safe_schedule_threadsafe
            future = safe_schedule_threadsafe(operation(adapter, args, chat_id), loop, logger=logger,
                                              log_message="Feishu read could not reach Gateway loop")
            if future is None:
                raise ValueError("Feishu Gateway loop is unavailable")
            result = await asyncio.wait_for(asyncio.wrap_future(future), timeout=120)
        else:
            result = await asyncio.wait_for(operation(adapter, args, chat_id), timeout=120)
        return tool_result(result)
    except PlatformReadError as exc:
        return tool_error(str(exc), code=exc.code,
                          hint="Check message read scopes (including im:message.group_msg for groups), app publication, bot membership and message visibility.")
    except (ValueError, TimeoutError) as exc:
        return tool_error(str(exc) or "Feishu read timed out")
    except Exception as exc:
        # SDK exceptions can carry authenticated URLs; expose only their type.
        return tool_error(f"Feishu read failed ({type(exc).__name__}); retry or inspect platform connectivity.")


async def messages(args, **kwargs):
    return await _handle(_read, args)


async def download(args, **kwargs):
    return await _handle(_download, args)


def register_tools(ctx):
    common = {"chat_id": {"type": "string", "description": "Feishu chat ID. Defaults to the current Feishu chat; use an explicit ID for another chat."}}
    tools = [
        ("feishu_messages", messages, "Find files or read messages in Feishu chats on demand. List newest first with pagination; get a known message by ID. Does not download attachments.", {
            **common, "action": {"type": "string", "enum": ["list", "get"]},
            "message_id": {"type": "string", "description": "Required for get."},
            "thread_id": {"type": "string", "description": "List a topic's replies rather than the whole chat."},
            "query": {"type": "string", "description": "Case-insensitive text/filename filter on this page only."},
            "attachments_only": {"type": "boolean"}, "page_size": {"type": "integer", "minimum": 1, "maximum": 50},
            "page_token": {"type": "string", "description": "Continue a previous list query with the same filters."},
            "start_time": {"type": "string", "description": "Inclusive Unix seconds, chat queries only."},
            "end_time": {"type": "string", "description": "Unix seconds, chat queries only."}}, []),
        ("feishu_download_attachment", download, "Download a Feishu message's attachments to native Hermes local cache; returns paths to read with file/terminal tools. Chat folders cannot be downloaded via OpenAPI.", {
            **common, "message_id": {"type": "string", "description": "From feishu_messages or the current message reference."}}, ["message_id"]),
    ]
    for name, handler, description, properties, required in tools:
        ctx.register_tool(name=name, toolset="feishu_files", handler=handler, is_async=True,
                          schema={"name": name, "description": description, "parameters": {
                              "type": "object", "properties": properties, "required": required}},
                          description=description, emoji="📎")
