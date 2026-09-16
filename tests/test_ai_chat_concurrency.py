from __future__ import annotations

import asyncio
import unittest
from typing import Any

import httpx
import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from src.plugins.ai_chat.config import Config
from src.plugins.ai_chat.data_source import ChatHandler, HERMES_UNCERTAIN_ERROR


class ControlledHandler(ChatHandler):
    def __init__(self, config: Config) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fallback_calls: list[list[dict[str, str]]] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.hermes_error: Exception | None = None
        super().__init__(config)
        self.fallback_client = object()

    async def _request_hermes(
        self, message: str, conversation_id: str, *_: Any
    ) -> dict[str, Any]:
        self.calls.append((conversation_id, message))
        gate = self.gates.get(message)
        if gate:
            await gate.wait()
        if self.hermes_error:
            raise self.hermes_error
        return {"output_text": f"hermes:{message}"}

    async def _request_fallback(
        self, history: list[dict[str, str]], *_: Any
    ) -> dict[str, str]:
        self.fallback_calls.append(history)
        return {"output_text": f"fallback:{history[-1]['content']}"}


def ask(handler: ChatHandler, message: str, conversation_id: str = "qq:u1") -> Any:
    return handler.ask(
        message,
        conversation_id,
        user_id=1,
        display_name="甲",
        group_id=100,
    )


class AIChatConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_session_is_serialized_without_resending_history(self) -> None:
        handler = ControlledHandler(Config(hermes_baseurl="http://hermes/v1", hermes_key="key"))
        handler.gates["first"] = asyncio.Event()
        first = asyncio.create_task(ask(handler, "first"))
        await asyncio.sleep(0)
        second = asyncio.create_task(ask(handler, "second"))
        await asyncio.sleep(0)
        self.assertEqual(handler.calls, [("qq:u1", "first")])
        handler.gates["first"].set()
        self.assertEqual(await asyncio.gather(first, second), ["hermes:first", "hermes:second"])
        self.assertEqual(handler.calls, [("qq:u1", "first"), ("qq:u1", "second")])
        self.assertEqual(handler.fallback_histories, {})

    async def test_connect_failure_uses_only_short_term_fallback_history(self) -> None:
        handler = ControlledHandler(
            Config(hermes_baseurl="http://hermes/v1", hermes_key="key", aichat_model="fallback")
        )
        handler.hermes_error = httpx.ConnectError("offline")
        self.assertEqual(await ask(handler, "first"), "fallback:first")
        self.assertEqual(await ask(handler, "second"), "fallback:second")
        self.assertEqual(
            [item["content"] for item in handler.fallback_calls[-1]],
            ["first", "fallback:first", "second"],
        )

    async def test_ambiguous_timeout_never_calls_fallback(self) -> None:
        handler = ControlledHandler(
            Config(hermes_baseurl="http://hermes/v1", hermes_key="key", aichat_model="fallback")
        )
        handler.hermes_error = httpx.ReadTimeout("uncertain")
        self.assertEqual(await ask(handler, "hello"), HERMES_UNCERTAIN_ERROR)
        self.assertEqual(handler.fallback_calls, [])

    async def test_hermes_recovery_clears_stale_fallback_context(self) -> None:
        handler = ControlledHandler(
            Config(hermes_baseurl="http://hermes/v1", hermes_key="key", aichat_model="fallback")
        )
        handler.hermes_error = httpx.ConnectError("offline")
        self.assertEqual(await ask(handler, "offline turn"), "fallback:offline turn")
        self.assertIn("qq:u1", handler.fallback_histories)
        handler.hermes_error = None
        self.assertEqual(await ask(handler, "online turn"), "hermes:online turn")
        self.assertNotIn("qq:u1", handler.fallback_histories)

    async def test_without_hermes_fallback_works_independently(self) -> None:
        handler = ControlledHandler(Config(aichat_model="fallback"))
        self.assertEqual(await ask(handler, "hello"), "fallback:hello")
        self.assertEqual(handler.calls, [])


if __name__ == "__main__":
    unittest.main()
