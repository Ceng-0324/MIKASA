"""Attachment ingress fix for pinned Hermes; retire when upstream covers quoted media.

Use the native platform registry and subclass its discovered adapter. Transport,
admission, downloads, cache, batching and agent execution remain owned by Hermes.
"""
import logging
from dataclasses import replace
from types import SimpleNamespace

logger = logging.getLogger(__name__)


class ReplyAttachments:
    def _normalize(self, message_type, raw_content, mentions):
        if str(message_type or "").strip().lower() == "folder":
            # Desktop folder uploads carry file_key/file_name too, but pinned
            # Hermes drops this type (and renders the parent as literal "None").
            # Reuse its file parser/downloader; metadata alone is not file access.
            normalized = super()._normalize("file", raw_content, mentions)
            return replace(normalized, raw_type="folder",
                           text_content="[飞书文件夹] " + normalized.metadata["placeholder_text"])
        return super()._normalize(message_type, raw_content, mentions)

    async def _fetch_message_resource(self, **kwargs):
        response = await super()._fetch_message_resource(**kwargs)
        if not response or not response.success():
            # The pinned adapter only logs API failures at DEBUG. Do not log
            # response bodies, credentials, URLs or user-provided file names.
            logger.warning("Feishu attachment download failed: code=%s",
                           getattr(response, "code", "unknown"))
        return response

    async def _extract_message_content(self, message):
        text, kind, paths, types, inlined, mentions = await super()._extract_message_content(message)
        normalized = self._normalize(getattr(message, "message_type", ""),
                                     getattr(message, "content", ""), getattr(message, "mentions", None))
        expected = len(normalized.image_keys) + len(normalized.media_refs)
        if len(paths) < expected:
            if normalized.raw_type == "folder":
                text += ("\n[飞书文件夹未取得内容：消息资源接口未能下载该文件夹，当前只有名称。"
                         "可将文件夹压缩为 ZIP 后发送，再引用 ZIP 并 @；不能据此分析文件内容。]")
            else:
                text += ("\n[飞书附件下载未完成：部分或全部文件未取得，不能据此判断文件内容。"
                         "请说明附件传输失败；检查平台权限或稍后引用原文件重试。]")
        return text, kind, paths, types, inlined, mentions

    async def _dispatch_inbound_event(self, event):
        if event.reply_to_message_id and not event.is_command():
            await self._attach_reply_resources(event)
        await super()._dispatch_inbound_event(event)

    async def _attach_reply_resources(self, event):
        try:
            request = self._build_get_message_request(event.reply_to_message_id)
            response = await self._run_blocking(self._client.im.v1.message.get, request)
            if not response or not response.success():
                logger.warning("Feishu quoted message lookup failed: code=%s",
                               getattr(response, "code", "unknown"))
                raise ValueError("message lookup failed")
            items = getattr(getattr(response, "data", None), "items", None) or []
            parent = next((item for item in items
                           if getattr(item, "message_id", None) == event.reply_to_message_id), None)
            if (parent is None or getattr(parent, "deleted", False)
                    or getattr(parent, "chat_id", None) != event.source.chat_id):
                raise ValueError("quoted message unavailable in this chat")
            message = SimpleNamespace(message_id=parent.message_id, message_type=parent.msg_type,
                                      content=getattr(parent.body, "content", ""),
                                      mentions=getattr(parent, "mentions", None))
            normalized = self._normalize(message.message_type, message.content, message.mentions)
            if not normalized.media_refs and not normalized.image_keys:
                return
            # Only the explicitly quoted message, never ancestors or chat history.
            # This also works when the standalone file event was never delivered.
            text, _, paths, types, inlined, _ = await self._extract_message_content(message)
            event.media_urls.extend(paths)
            event.media_types.extend(types)
            event.media_text_inlined.extend(inlined)
            if text:
                event.text += "\n\n[引用消息的附件内容]\n" + text
        except Exception as exc:
            logger.warning("Feishu quoted attachment retrieval failed: %s", type(exc).__name__)
            event.text += "\n[飞书引用消息读取失败，无法确认其中的附件；不要声称已读取文件。]"


def install_attachment_support():
    """Preserve every native platform capability; replace only its ingress factory."""
    from gateway.platform_registry import platform_registry
    entry = platform_registry.get("feishu")
    if entry is None:
        raise RuntimeError("Pinned Hermes Feishu platform is unavailable")
    if issubclass(entry.adapter_factory, ReplyAttachments):
        return

    class FeishuAttachmentAdapter(ReplyAttachments, entry.adapter_factory):
        pass

    platform_registry.register(replace(entry, adapter_factory=FeishuAttachmentAdapter),
                               scope=platform_registry.current_scope_key())
