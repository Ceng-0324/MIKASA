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
from workers.hermes.feishu_ingress import install_ingress_support

discover_plugins()
native_entry = platform_registry.get("feishu")
NativeAdapter = native_entry.adapter_factory
native_module = sys.modules[NativeAdapter.__module__]
native_module._load_lark_oapi()
install_ingress_support()


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
        self.source = self.adapter.build_source(chat_id="oc_room", chat_type="group", user_id="ou_sender",
                                                user_name="sender", thread_id="omt_topic")

    def quoted(self, **kwargs):
        return MessageEvent(text="分析这份项目", source=self.source, reply_to_message_id="om_file",
                            reply_to_text="[Attachment: project.zip]", message_id="om_request", **kwargs)

    async def test_quoted_zip_reaches_native_agent_context_without_original_file_event(self):
        event = self.quoted()
        await self.adapter._dispatch_inbound_event(event)
        self.dispatch.assert_awaited_once_with(event)
        self.assertEqual(len(event.media_urls), 1)
        self.assertEqual(Path(event.media_urls[0]).read_bytes(), b"archive fixture")
        self.assertEqual(event.media_text_inlined, [False])
        self.assertEqual(event.source.thread_id, "omt_topic")
        self.assertEqual(event.reply_to_text, "[Attachment: project.zip]")
        # The actual native Gateway prompt builder must carry the usable path.
        from gateway.run_inbound import GatewayInboundMixin
        prompt = GatewayInboundMixin._prepend_inbound_document_notes(event, event.text)
        self.assertIn(event.media_urls[0], prompt)
        self.assertIn("project.zip", prompt)
        self.assertIn("分析这份项目", prompt)

    async def test_direct_zip_keeps_native_download(self):
        incoming = N(message_id="om_direct", message_type="file", mentions=[],
                     content=json.dumps({"file_key": "file_fixture", "file_name": "project.zip"}))
        _, kind, paths, types, flags, _ = await self.adapter._extract_message_content(incoming)
        self.assertEqual(kind, MessageType.DOCUMENT)
        self.assertEqual(Path(paths[0]).read_bytes(), b"archive fixture")
        self.assertEqual(types, ["application/zip"])
        self.assertEqual(flags, [False])
        self.adapter._client.im.v1.message.get.assert_not_called()

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
        with self.assertLogs("workers.hermes.feishu_ingress", level="WARNING") as logs:
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
        install_ingress_support()
        self.assertIs(platform_registry.get("feishu"), fixed)
        self.assertIsInstance(self.adapter, NativeAdapter)
        for name in vars(native_entry):
            if name != "adapter_factory":
                self.assertEqual(getattr(fixed, name), getattr(native_entry, name), name)


class GroupContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = platform_registry.create_adapter("feishu", PlatformConfig(extra={
            "app_id": "fixture", "require_mention": True, "default_group_policy": "open"}))
        self.dispatch = self.enterContext(patch.object(NativeAdapter, "_dispatch_inbound_event", AsyncMock()))
        self.history = self.enterContext(patch.object(NativeAdapter, "_tenant_get_raw", AsyncMock()))
        self.source = self.adapter.build_source(chat_id="oc_room", chat_type="group", user_id="ou_sender",
                                                user_name="sender")

    def event(self, text="刚才大家在讨论什么？"):
        return MessageEvent(text=text, source=self.source, message_id="om_trigger",
                            raw_message=N(event=N(message=N(create_time="2000999"))))

    def row(self, mid="om_background", text="讨论项目部署", **extra):
        return {"message_id": mid, "chat_id": "oc_room", "create_time": "2000100", "msg_type": "text",
                "sender": {"id": "ou_other", "sender_type": "user", "id_type": "open_id"},
                "body": {"content": json.dumps({"text": text})}, **extra}

    def rows(self, *items):
        self.history.return_value = json.dumps({"code": 0, "data": {"items": items}})

    async def test_recent_unmentioned_messages_enter_native_context_in_order(self):
        self.rows(self.row("om_later", "决定明天部署"), self.row("om_earlier", "讨论项目部署", create_time="2000000"))
        event = self.event()
        await self.adapter._dispatch_inbound_event(event)
        self.assertEqual(event.text, "刚才大家在讨论什么？")
        self.assertIn("ou_other", event.channel_context)
        self.assertLess(event.channel_context.index("讨论项目部署"), event.channel_context.index("决定明天部署"))
        from gateway.run_inbound import GatewayInboundMixin
        runner = GatewayInboundMixin()
        runner.config = N(group_sessions_per_user=False, thread_sessions_per_user=False)
        prompt = runner._prefix_inbound_sender_context(event, event.source, event.text)
        self.assertIn("[New message]\n[sender] 刚才大家在讨论什么？", prompt)
        self.assertIn("讨论项目部署", prompt)
        query = dict(self.history.call_args.kwargs["queries"])
        self.assertEqual(query["container_id_type"], "chat")
        self.assertEqual(query["container_id"], "oc_room")
        self.assertEqual(query["end_time"], "2001")
        self.dispatch.assert_awaited_once_with(event)

    async def test_history_never_crosses_chat_thread_or_trigger_boundary(self):
        self.rows(self.row(), self.row(), self.row("om_trigger"),
                  self.row("om_future", create_time="2001000"), self.row("om_deleted", deleted=True),
                  self.row("om_other_chat", chat_id="oc_other"), self.row("om_other_thread", thread_id="omt_other"))
        event = self.event()
        await self.adapter._dispatch_inbound_event(event)
        self.assertEqual(event.channel_context.count('"message_id"'), 1)
        for word in ("om_trigger", "om_future", "om_deleted", "om_other_chat", "om_other_thread"):
            self.assertNotIn(word, event.channel_context)
        self.source.thread_id = "omt_topic"
        self.rows(self.row("om_topic", thread_id="omt_topic"), self.row("om_outside"))
        event = self.event()
        await self.adapter._dispatch_inbound_event(event)
        self.assertIn("om_topic", event.channel_context)
        self.assertNotIn("om_outside", event.channel_context)
        query = dict(self.history.call_args.kwargs["queries"])
        self.assertEqual((query["container_id_type"], query["container_id"]), ("thread", "omt_topic"))

    async def test_dm_and_commands_do_not_fetch_history(self):
        self.rows(self.row(text="/new"))
        event = self.event("/help")
        await self.adapter._dispatch_inbound_event(event)
        self.source.chat_type = "dm"
        await self.adapter._dispatch_inbound_event(self.event())
        self.history.assert_not_awaited()

    async def test_background_commands_and_attachments_remain_context_only(self):
        self.rows(self.row(text="/new"), self.row("om_file", msg_type="file", body={"content": json.dumps({
            "file_key": "file_fixture", "file_name": "project.zip"})}))
        event = self.event()
        with patch.object(NativeAdapter, "_fetch_message_resource", AsyncMock()) as download:
            await self.adapter._dispatch_inbound_event(event)
        download.assert_not_awaited()
        self.assertFalse(event.is_command())
        self.assertIn("/new", event.channel_context)
        self.assertIn("project.zip", event.channel_context)
        self.assertFalse(event.media_urls)

    async def test_history_is_bounded_and_does_not_create_local_history(self):
        self.rows(*(self.row(f"om_{i}", "x" * 3000) for i in range(100)))
        event = self.event()
        await self.adapter._dispatch_inbound_event(event)
        self.assertLess(len(event.channel_context), 12200)
        self.assertLessEqual(event.channel_context.count('"message_id"'), 20)
        self.assertIn("截断", event.channel_context)
        self.assertEqual(dict(self.history.call_args.kwargs["queries"])["page_size"], "20")
        self.history.assert_awaited_once()

    async def test_history_failure_keeps_current_message_and_can_retry(self):
        for reply in (json.dumps({"code": 230027, "msg": "private response"}), "not json"):
            self.history.return_value = reply
            event = self.event()
            with self.assertLogs("workers.hermes.feishu_ingress", level="WARNING") as logs:
                await self.adapter._dispatch_inbound_event(event)
            self.assertIn("读取失败", event.channel_context)
            self.assertEqual(event.text, "刚才大家在讨论什么？")
            self.assertNotIn("private response", " ".join(logs.output))
        self.rows(self.row())
        event = self.event()
        await self.adapter._dispatch_inbound_event(event)
        self.assertIn("讨论项目部署", event.channel_context)
        self.assertEqual(self.dispatch.await_count, 3)

    async def test_history_timeout_is_visible_and_cancellation_propagates(self):
        self.history.side_effect = TimeoutError
        event = self.event()
        with self.assertLogs("workers.hermes.feishu_ingress", level="WARNING"):
            await self.adapter._dispatch_inbound_event(event)
        self.assertIn("读取失败", event.channel_context)
        self.dispatch.reset_mock()
        self.history.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.adapter._dispatch_inbound_event(self.event())
        self.dispatch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
