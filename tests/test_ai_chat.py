import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import nonebot

nonebot.init()

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.event import Reply
from src.common.rules import message_mentions_bot
from src.plugins.ai_chat import (
    _build_prompt_with_reply,
    _extract_chat_content,
    _extract_reply_context,
    _format_memory_list,
    _parse_forget_command,
    _parse_remember_command,
)
from src.plugins.ai_chat.config import Config
from src.plugins.ai_chat.data_source import ChatHandler
from src.plugins.ai_chat.memory_store import MemoryStore
from src.plugins.ai_chat.role_store import DEFAULT_ROLES


class _RoleStore:
    def get_prompt(self, role_name: str) -> str:
        return f"role:{role_name}"


class _Responses:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.responses = responses or ["ok"]

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return SimpleNamespace(output_text=response)


class _Client:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = _Responses(responses)


class _SummaryHandler(ChatHandler):
    def __init__(self, config: Config, role_store: _RoleStore, memory_store: MemoryStore | None = None) -> None:
        super().__init__(config, role_store, memory_store)
        self.scheduled_summaries: list[tuple[str, list[dict[str, str]]]] = []

    def _schedule_memory_summary(self, memory_scope: str, recent_turns: list[dict[str, str]]) -> None:
        self.scheduled_summaries.append((memory_scope, recent_turns))


class AiChatTestCase(unittest.TestCase):
    def test_default_roles_include_jarvis_preset(self) -> None:
        self.assertIn("jarvis", DEFAULT_ROLES)
        self.assertIn("英式管家", DEFAULT_ROLES["jarvis"])

    def test_message_mentions_bot_finds_at_segment_anywhere(self) -> None:
        message = Message(
            [
                MessageSegment.image("https://example.com/a.jpg"),
                MessageSegment.at("12345"),
                MessageSegment.text(" hello"),
            ]
        )

        self.assertTrue(message_mentions_bot(message, SimpleNamespace(self_id="12345")))
        self.assertFalse(message_mentions_bot(message, SimpleNamespace(self_id="67890")))

    def test_extract_chat_content_ignores_reply_segment(self) -> None:
        message = Message([MessageSegment.reply(42), MessageSegment.text(" 总结一下")])

        prompt, image_urls = _extract_chat_content(message, SimpleNamespace(self_id="12345"))

        self.assertEqual(prompt, "总结一下")
        self.assertEqual(image_urls, [])

    def test_extract_reply_context_includes_quoted_text_and_images(self) -> None:
        reply = Reply(
            time=1,
            message_type="group",
            message_id=42,
            real_id=42,
            sender={"user_id": 10001, "nickname": "茗懿"},
            message=Message(
                [
                    MessageSegment.text("这张图是新闻截图"),
                    MessageSegment("image", {"file": "https://example.com/news.png"}),
                ]
            ),
        )

        reply_context, image_urls = _extract_reply_context(reply, SimpleNamespace(self_id="12345"))

        self.assertEqual(reply_context, "用户引用了 茗懿 的消息：这张图是新闻截图 [image]")
        self.assertEqual(image_urls, ["https://example.com/news.png"])

    def test_build_prompt_with_reply_context(self) -> None:
        self.assertEqual(
            _build_prompt_with_reply("总结一下", "用户引用了 茗懿 的消息：[image]"),
            "用户引用了 茗懿 的消息：[image]\n用户当前消息：总结一下",
        )

    def test_memory_command_helpers(self) -> None:
        self.assertEqual(_parse_remember_command("记住 我喜欢简洁回答"), "我喜欢简洁回答")
        self.assertEqual(_parse_remember_command("记住"), "")
        self.assertIsNone(_parse_remember_command("jarvis"))
        self.assertEqual(_parse_forget_command("忘记 1"), "1")
        self.assertEqual(_parse_forget_command("忘记 全部"), "全部")
        self.assertEqual(
            _format_memory_list([{"id": "1", "content": "用户喜欢简洁回答"}]),
            "当前长期记忆：\n1. 用户喜欢简洁回答",
        )

    def test_memory_store_adds_deduplicates_deletes_and_clears(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(str(Path(temp_dir) / "memories.json"), max_items=20)

            first = store.add_memory("user:1", "  用户喜欢简洁回答  ")
            duplicate = store.add_memory("user:1", "用户喜欢简洁回答")

            self.assertEqual(first["id"], duplicate["id"])
            self.assertEqual(store.list_memories("user:1")[0]["content"], "用户喜欢简洁回答")
            self.assertTrue(store.delete_memory("user:1", first["id"]))
            self.assertFalse(store.delete_memory("user:1", first["id"]))
            self.assertEqual(store.list_memories("user:1"), [])

            store.add_memory("user:1", "用户正在做 QQ 机器人")
            self.assertEqual(store.clear_memories("user:1"), 1)
            self.assertEqual(store.clear_memories("user:1"), 0)

    def test_memory_store_trims_to_max_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(str(Path(temp_dir) / "memories.json"), max_items=2)

            store.add_memory("user:1", "记忆一")
            store.add_memory("user:1", "记忆二")
            store.add_memory("user:1", "记忆三")

            memories = store.list_memories("user:1")
            self.assertEqual(len(memories), 2)
            self.assertEqual([item["content"] for item in memories], ["记忆二", "记忆三"])

    def test_ask_uses_responses_api_with_web_search(self) -> None:
        config = Config(
            aichat_key="key",
            aichat_baseurl="https://api.example/v1",
            aichat_model="gpt-5",
            aichat_web_search=True,
        )
        handler = ChatHandler(config, _RoleStore())
        client = _Client()
        handler.client = client

        response = asyncio.run(handler.ask("news?", "session", "default"))

        self.assertEqual(response, "ok")
        self.assertEqual(client.responses.calls[0]["model"], "gpt-5")
        self.assertIn("role:default", client.responses.calls[0]["instructions"])
        self.assertIn("当前日期时间", client.responses.calls[0]["instructions"])
        self.assertIn("天气、新闻", client.responses.calls[0]["instructions"])
        self.assertEqual(
            client.responses.calls[0]["input"],
            [{"role": "user", "content": [{"type": "input_text", "text": "news?"}]}],
        )
        self.assertEqual(client.responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(client.responses.calls[0]["tool_choice"], "auto")
        self.assertFalse(client.responses.calls[0]["stream"])

    def test_ask_uses_responses_api_without_web_search(self) -> None:
        config = Config(
            aichat_key="key",
            aichat_baseurl="https://api.example/v1",
            aichat_model="gpt-5",
            aichat_web_search=False,
        )
        handler = ChatHandler(config, _RoleStore())
        client = _Client()
        handler.client = client

        asyncio.run(handler.ask("hello", "session", "default"))

        self.assertNotIn("tools", client.responses.calls[0])
        self.assertNotIn("tool_choice", client.responses.calls[0])

    def test_ask_injects_enabled_user_memory_into_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(str(Path(temp_dir) / "memories.json"))
            store.add_memory("user:1", "用户喜欢简洁回答")
            config = Config(
                aichat_key="key",
                aichat_baseurl="https://api.example/v1",
                aichat_model="gpt-5",
            )
            handler = ChatHandler(config, _RoleStore(), store)
            client = _Client()
            handler.client = client

            asyncio.run(handler.ask("hello", "session", "default", memory_scope="user:1"))

            instructions = client.responses.calls[0]["instructions"]
            self.assertIn("已知用户长期记忆", instructions)
            self.assertIn("用户喜欢简洁回答", instructions)
            self.assertIn("不要把它们当作实时事实来源", instructions)

    def test_ask_skips_memory_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(str(Path(temp_dir) / "memories.json"))
            store.add_memory("user:1", "用户喜欢简洁回答")
            config = Config(
                aichat_key="key",
                aichat_baseurl="https://api.example/v1",
                aichat_model="gpt-5",
                aichat_memory_enabled=False,
            )
            handler = ChatHandler(config, _RoleStore(), store)
            client = _Client()
            handler.client = client

            asyncio.run(handler.ask("hello", "session", "default", memory_scope="user:1"))

            self.assertNotIn("已知用户长期记忆", client.responses.calls[0]["instructions"])

    def test_memory_summary_is_scheduled_every_three_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(str(Path(temp_dir) / "memories.json"))
            config = Config(
                aichat_key="key",
                aichat_baseurl="https://api.example/v1",
                aichat_model="gpt-5",
                aichat_memory_summary_interval=3,
            )
            handler = _SummaryHandler(config, _RoleStore(), store)
            handler.client = _Client()

            async def run_turns() -> None:
                await handler.ask("u1", "session", "default", memory_scope="user:1")
                await handler.ask("u2", "session", "default", memory_scope="user:1")
                await handler.ask("u3", "session", "default", memory_scope="user:1")

            asyncio.run(run_turns())

            self.assertEqual(len(handler.scheduled_summaries), 1)
            memory_scope, recent_turns = handler.scheduled_summaries[0]
            self.assertEqual(memory_scope, "user:1")
            self.assertEqual([item["content"] for item in recent_turns], ["u1", "ok", "u2", "ok", "u3", "ok"])

    def test_extract_memory_summaries_supports_json_response(self) -> None:
        config = Config(aichat_key="key", aichat_baseurl="https://api.example/v1", aichat_model="gpt-5")
        handler = ChatHandler(config, _RoleStore())

        response = SimpleNamespace(output_text='{"memories":["用户喜欢短回答"],"forget":[]}')

        self.assertEqual(handler._extract_memory_summaries(response), ["用户喜欢短回答"])

    def test_current_turn_images_are_sent_as_input_images(self) -> None:
        config = Config(
            aichat_key="key",
            aichat_baseurl="https://api.example/v1",
            aichat_model="gpt-5",
            aichat_web_search=True,
        )
        handler = ChatHandler(config, _RoleStore())
        client = _Client()
        handler.client = client

        asyncio.run(handler.ask("what is in this image?", "session", "default", ["https://example.com/a.jpg"]))

        self.assertEqual(
            client.responses.calls[0]["input"],
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "what is in this image?"},
                        {"type": "input_image", "image_url": "https://example.com/a.jpg", "detail": "auto"},
                    ],
                }
            ],
        )

    def test_extract_content_supports_dict_responses_output(self) -> None:
        config = Config(aichat_key="key", aichat_baseurl="https://api.example/v1", aichat_model="gpt-5")
        handler = ChatHandler(config, _RoleStore())

        response = {
            "output": [
                {"type": "web_search_call", "id": "ws_123"},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "search result"},
                    ],
                },
            ]
        }

        self.assertEqual(handler._extract_content(response), "search result")

    def test_extract_content_supports_sse_response_text(self) -> None:
        config = Config(aichat_key="key", aichat_baseurl="https://api.example/v1", aichat_model="gpt-5")
        handler = ChatHandler(config, _RoleStore())
        response = "\n".join(
            [
                'event: response.created',
                'data: {"type":"response.created","response":{"status":"in_progress","output":[]}}',
                '',
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","delta":"hello"}',
                '',
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","delta":" there"}',
                '',
                'event: response.completed',
                'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"hello there"}]}]}}',
            ]
        )

        self.assertEqual(handler._extract_content(response), "hello there")

    def test_responses_input_uses_output_text_for_assistant_history(self) -> None:
        config = Config(aichat_key="key", aichat_baseurl="https://api.example/v1", aichat_model="gpt-5")
        handler = ChatHandler(config, _RoleStore())

        self.assertEqual(
            handler._responses_input(
                [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                    {"role": "user", "content": "news?"},
                ]
            ),
            [
                {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
                {"role": "assistant", "content": [{"type": "output_text", "text": "hi"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "news?"}]},
            ],
        )

    def test_trim_history_keeps_complete_recent_turns(self) -> None:
        config = Config(
            aichat_key="key",
            aichat_baseurl="https://api.example/v1",
            aichat_model="gpt-5",
            aichat_history_limit=6,
        )
        handler = ChatHandler(config, _RoleStore())
        handler.histories["session"] = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
            {"role": "assistant", "content": "a3"},
        ]

        handler._trim_history("session", "system prompt")

        self.assertEqual(
            handler.histories["session"],
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "u2"},
                {"role": "assistant", "content": "a2"},
                {"role": "user", "content": "u3"},
                {"role": "assistant", "content": "a3"},
            ],
        )

    def test_retryable_error_detection_skips_normal_client_errors(self) -> None:
        config = Config(aichat_key="key", aichat_baseurl="https://api.example/v1", aichat_model="gpt-5")
        handler = ChatHandler(config, _RoleStore())

        self.assertFalse(handler._is_retryable_error(SimpleNamespace(status_code=400)))
        self.assertFalse(handler._is_retryable_error(SimpleNamespace(status_code=401)))
        self.assertTrue(handler._is_retryable_error(SimpleNamespace(status_code=429)))
        self.assertTrue(handler._is_retryable_error(SimpleNamespace(status_code=500)))
        self.assertTrue(handler._is_retryable_error(Exception("network")))


if __name__ == "__main__":
    unittest.main()
