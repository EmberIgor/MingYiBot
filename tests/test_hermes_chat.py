from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx
import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from src.plugins.ai_chat.config import Config
from src.plugins.ai_chat.data_source import ChatHandler
from src.plugins.ai_chat import _conversation_id


class HermesChatTest(unittest.IsolatedAsyncioTestCase):
    async def test_group_and_private_conversations_are_distinct(self) -> None:
        group = GroupMessageEvent.model_construct(group_id=100, user_id=200)
        other_group = GroupMessageEvent.model_construct(group_id=101, user_id=200)
        private = PrivateMessageEvent.model_construct(user_id=200)
        self.assertEqual(_conversation_id(group), "mingyi:qq:group:100:user:200")
        self.assertNotEqual(_conversation_id(group), _conversation_id(other_group))
        self.assertEqual(_conversation_id(private), "mingyi:qq:private:user:200")

    async def test_request_contains_current_turn_identity_and_image(self) -> None:
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "**你好**"}]}]},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        handler = ChatHandler(
            Config(
                hermes_baseurl="http://hermes:8642/v1",
                hermes_key="private-key",
                hermes_model="mingyi-public",
            )
        )
        with patch("src.plugins.ai_chat.data_source.httpx.AsyncClient", return_value=client):
            result = await handler.ask(
                "你好",
                "mingyi:qq:group:100:user:200",
                user_id=200,
                display_name="小明",
                group_id=100,
                image_urls=["https://example.com/p.png"],
            )

        self.assertEqual(result, "你好")
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url), "http://hermes:8642/v1/responses")
        self.assertEqual(request.headers["authorization"], "Bearer private-key")
        body = json.loads(request.content)
        self.assertEqual(body["conversation"], "mingyi:qq:group:100:user:200")
        self.assertEqual(body["model"], "mingyi-public")
        self.assertEqual(len(body["input"]), 1)
        content = body["input"][0]["content"]
        self.assertIn("发言者QQ号：200", content[0]["text"])
        self.assertIn('发言者显示名："小明"', content[0]["text"])
        self.assertIn("真实发言者 QQ 号是 200", body["instructions"])
        self.assertIn("来源：QQ群 100", content[0]["text"])
        self.assertEqual(content[1]["image_url"], "https://example.com/p.png")
        self.assertEqual(handler.fallback_histories, {})

    async def test_hermes_http_error_does_not_switch_backend(self) -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"error": "bad key"}))
        )
        handler = ChatHandler(
            Config(hermes_baseurl="http://hermes/v1", hermes_key="wrong", aichat_model="fallback")
        )
        with patch("src.plugins.ai_chat.data_source.httpx.AsyncClient", return_value=client):
            result = await handler.ask(
                "你好", "mingyi:qq:private:user:200", user_id=200, display_name="小明", group_id=None
            )
        self.assertIn("失败", result)
        self.assertEqual(handler.fallback_histories, {})


if __name__ == "__main__":
    unittest.main()
