"""Run through test_connections using the pinned Hermes interpreter."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as N
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [os.environ["MIKASA_HERMES_SOURCE"], str(ROOT)]

from hermes_cli.plugins import discover_plugins
from gateway.config import PlatformConfig
from gateway.platform_registry import platform_registry
from gateway.platforms.event import MessageEvent, MessageType
from workers.hermes.feishu_attachments import install_attachment_support

discover_plugins()
native_entry = platform_registry.get("feishu")
NativeAdapter = native_entry.adapter_factory
native_module = sys.modules[NativeAdapter.__module__]
native_module._load_lark_oapi()
install_attachment_support()


def success(**data):
    return N(success=lambda: True, code=0, data=N(**data))


def message(kind="file", content=None, **extra):
    return N(message_id="om_file", msg_type=kind, chat_id="oc_room", deleted=False,
             body=N(content=json.dumps(content or {"file_key": "file_fixture", "file_name": "project.zip"})),
             **extra)


class AttachmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = platform_registry.create_adapter("feishu", PlatformConfig(extra={"app_id": "fixture"}))
        self.adapter._client = N(im=N(v1=N(message=N(get=Mock(return_value=success(items=[message()]))))))
        self.resource = N(success=lambda: True, code=0, file=io.BytesIO(b"archive fixture"),
                          file_name="project.zip", raw=N(headers={"Content-Type": "application/zip"}))
        self.fetch = self.enterContext(patch.object(NativeAdapter, "_fetch_message_resource", AsyncMock(return_value=self.resource)))
        self.dispatch = self.enterContext(patch.object(NativeAdapter, "_dispatch_inbound_event", AsyncMock()))
        self.history = self.enterContext(patch.object(NativeAdapter, "_tenant_get_raw", AsyncMock()))
        self.source = self.adapter.build_source(chat_id="oc_room", chat_type="group", user_id="ou_sender",
                                                user_name="sender", thread_id="omt_topic")

    def quoted(self, **kwargs):
        return MessageEvent(text="分析这份项目", source=self.source, reply_to_message_id="om_file",
                            reply_to_text="[Attachment: project.zip]", message_id="om_request",
                            raw_message=N(event=N(message=N(create_time="2000999"))), **kwargs)

    async def test_quoted_zip_reaches_native_agent_context_without_original_file_event(self):
        event = self.quoted()
        await self.adapter._dispatch_inbound_event(event)
        self.dispatch.assert_awaited_once_with(event)
        self.assertEqual(len(event.media_urls), 1)
        self.assertEqual(Path(event.media_urls[0]).read_bytes(), b"archive fixture")
        self.assertEqual(event.media_text_inlined, [False])
        self.assertEqual(event.source.thread_id, "omt_topic")
        self.assertEqual(event.reply_to_text, "[Attachment: project.zip]")
        self.history.assert_not_awaited()
        self.assertIsNone(event.channel_context)
        # The actual native Gateway prompt builder must carry the usable path.
        from gateway.run_inbound import GatewayInboundMixin
        prompt = GatewayInboundMixin._prepend_inbound_document_notes(event, event.text)
        self.assertIn(event.media_urls[0], prompt)
        self.assertIn("project.zip", prompt)
        self.assertIn("分析这份项目", prompt)

    async def test_plain_group_message_keeps_native_context_without_history_lookup(self):
        event = MessageEvent(text="你好", source=self.source, message_id="om_hello",
                             raw_message=N(event=N(message=N(create_time="2000999"))))
        await self.adapter._dispatch_inbound_event(event)
        self.history.assert_not_awaited()
        self.adapter._client.im.v1.message.get.assert_not_called()
        self.fetch.assert_not_awaited()
        self.assertIsNone(event.channel_context)
        self.assertEqual(event.text, "你好")
        self.dispatch.assert_awaited_once_with(event)

    async def test_direct_zip_keeps_native_download(self):
        incoming = N(message_id="om_direct", message_type="file", mentions=[],
                     content=json.dumps({"file_key": "file_fixture", "file_name": "project.zip"}))
        _, kind, paths, types, flags, _ = await self.adapter._extract_message_content(incoming)
        self.assertEqual(kind, MessageType.DOCUMENT)
        self.assertEqual(Path(paths[0]).read_bytes(), b"archive fixture")
        self.assertEqual(types, ["application/zip"])
        self.assertEqual(flags, [False])
        self.adapter._client.im.v1.message.get.assert_not_called()

    async def test_raw_group_quote_preserves_folder_name_and_reports_api_failure(self):
        # Feishu's desktop folder upload is type=folder, even though the UI says
        # [file]. Exercise admission and native parent parsing, not a prebuilt event.
        self.adapter._bot_open_id = "ou_bot"
        self.adapter._require_mention = True
        self.adapter._default_group_policy = "open"
        self.adapter.get_chat_info = AsyncMock(return_value={"name": "room"})
        self.adapter._resolve_sender_profile = AsyncMock(return_value={
            "user_id": "ou_sender", "user_name": "sender", "user_id_alt": None})
        self.adapter._client.im.v1.message.get.return_value = success(items=[
            message("folder", {"file_key": "file_fixture", "file_name": "project-folder"})])
        self.fetch.return_value = N(success=lambda: False, code=40009)
        incoming = N(message_id="om_unmentioned", message_type="text", chat_type="group",
                     chat_id="oc_room", parent_id="om_file", mentions=[],
                     content=json.dumps({"text": "分析这个项目"}))
        data = N(event=N(message=incoming, sender=N(sender_type="user",
                         sender_id=N(open_id="ou_sender"))))
        await self.adapter._handle_message_event_data(data)
        self.dispatch.assert_not_awaited()
        self.adapter._client.im.v1.message.get.assert_not_called()
        incoming.message_id = "om_mentioned"
        incoming.mentions = [N(key="@_user_1", name="Mikasa", id=N(open_id="ou_bot"))]
        incoming.content = json.dumps({"text": "@_user_1 分析这个项目"})
        await self.adapter._handle_message_event_data(data)
        event = self.dispatch.await_args.args[0]
        self.assertIn("project-folder", event.reply_to_text)
        self.assertNotEqual(event.reply_to_text, "None")
        self.assertIn("project-folder", event.text)
        self.assertIn("文件夹", event.text)
        self.assertIn("ZIP", event.text)
        self.assertFalse(event.media_urls)
        self.fetch.assert_awaited_once_with(message_id="om_file", file_key="file_fixture", resource_type="file")
        self.history.assert_not_awaited()
        self.assertIsNone(event.channel_context)

    async def test_direct_folder_uses_native_downloader_and_preserves_failure(self):
        incoming = N(message_id="om_folder", message_type="folder", mentions=[],
                     content=json.dumps({"file_key": "file_fixture", "file_name": "project-folder"}))
        self.fetch.return_value = N(success=lambda: False, code=40009)
        text, kind, paths, _, _, _ = await self.adapter._extract_message_content(incoming)
        self.assertEqual(kind, MessageType.DOCUMENT)
        self.assertFalse(paths)
        self.assertIn("project-folder", text)
        self.assertIn("ZIP", text)
        # If the platform supplies bytes, the same native cache/context path works.
        self.fetch.return_value = self.resource
        text, _, paths, _, _, _ = await self.adapter._extract_message_content(incoming)
        self.assertEqual(Path(paths[0]).read_bytes(), b"archive fixture")
        self.assertNotIn("未取得", text)

    async def test_quoted_text_and_new_attachments_are_preserved(self):
        self.resource.file_name = "notes.md"
        self.resource.file = io.BytesIO(b"quoted document content")
        self.resource.raw.headers["Content-Type"] = "text/markdown"
        event = self.quoted(media_urls=["/tmp/new.zip"], media_types=["application/zip"], media_text_inlined=[False])
        await self.adapter._dispatch_inbound_event(event)
        self.assertEqual(event.media_urls[0], "/tmp/new.zip")
        self.assertEqual(len(event.media_urls), 2)
        self.assertEqual(event.media_text_inlined, [False, True])
        self.assertIn("quoted document content", event.text)

    async def test_rich_message_downloads_each_attachment_without_recursing(self):
        parent = message("post", {"zh_cn": {"title": "archives", "content": [[
            {"tag": "file", "file_key": "file_a", "file_name": "a.zip"},
            {"tag": "file", "file_key": "file_b", "file_name": "b.zip"}]]}}, parent_id="om_older")
        self.adapter._client.im.v1.message.get.return_value = success(items=[parent])
        event = self.quoted()
        await self.adapter._dispatch_inbound_event(event)
        self.assertEqual(len(event.media_urls), 2)
        self.assertEqual(self.fetch.await_count, 2)
        self.adapter._client.im.v1.message.get.assert_called_once()

    async def test_commands_do_not_fetch_quoted_files(self):
        event = self.quoted()
        event.text = "/new"
        await self.adapter._dispatch_inbound_event(event)
        self.adapter._client.im.v1.message.get.assert_not_called()
        self.fetch.assert_not_awaited()
        self.assertEqual(event.text, "/new")
        self.dispatch.assert_awaited_once_with(event)

    async def test_missing_deleted_and_foreign_chat_files_are_not_downloaded(self):
        foreign, deleted = message(), message()
        foreign.chat_id, deleted.deleted = "oc_other", True
        for items in ([], [foreign], [deleted]):
            with self.subTest(items=items):
                self.adapter._client.im.v1.message.get.return_value = success(items=items)
                event = self.quoted()
                await self.adapter._dispatch_inbound_event(event)
                self.assertFalse(event.media_urls)
                self.assertIn("引用消息读取失败", event.text)
        self.fetch.assert_not_awaited()

    async def test_permission_failure_is_visible_and_next_request_can_retry(self):
        self.fetch.return_value = N(success=lambda: False, code=99991672, msg="private response")
        event = self.quoted()
        with self.assertLogs("workers.hermes.feishu_attachments", level="WARNING") as logs:
            await self.adapter._dispatch_inbound_event(event)
        self.assertIn("99991672", " ".join(logs.output))
        self.assertNotIn("private response", " ".join(logs.output))
        self.assertFalse(event.media_urls)
        self.assertIn("附件下载未完成", event.text)
        self.fetch.return_value = self.resource
        retry = self.quoted()
        await self.adapter._dispatch_inbound_event(retry)
        self.assertTrue(retry.media_urls)

    async def test_lookup_failure_preserves_original_message(self):
        self.adapter._client.im.v1.message.get.return_value = N(success=lambda: False, code=230001)
        event = self.quoted()
        await self.adapter._dispatch_inbound_event(event)
        self.assertTrue(event.text.startswith("分析这份项目"))
        self.assertIn("引用消息读取失败", event.text)
        self.dispatch.assert_awaited_once_with(event)

    async def test_cancellation_propagates_without_dispatch(self):
        self.fetch.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.adapter._dispatch_inbound_event(self.quoted())
        self.dispatch.assert_not_awaited()

    async def test_native_platform_contract_is_preserved_and_install_is_idempotent(self):
        fixed = platform_registry.get("feishu")
        install_attachment_support()
        self.assertIs(platform_registry.get("feishu"), fixed)
        self.assertIsInstance(self.adapter, NativeAdapter)
        for name in vars(native_entry):
            if name != "adapter_factory":
                self.assertEqual(getattr(fixed, name), getattr(native_entry, name), name)


if __name__ == "__main__":
    unittest.main()
