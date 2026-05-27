import asyncio
import unittest
from types import SimpleNamespace

import nonebot

nonebot.init()

from src.plugins.ai_chat.config import Config
from src.plugins.ai_chat.data_source import ChatHandler


class _RoleStore:
    def get_prompt(self, role_name: str) -> str:
        return f"role:{role_name}"


class _Responses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="ok")


class _Client:
    def __init__(self) -> None:
        self.responses = _Responses()


class AiChatTestCase(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
