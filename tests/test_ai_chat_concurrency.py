from __future__ import annotations

import asyncio
import unittest
from typing import Any

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from src.plugins.ai_chat.config import Config
from src.plugins.ai_chat.data_source import ChatHandler


class StubRoleStore:
    def get_prompt(self, role_name: str) -> str:
        return f"prompt:{role_name}"


class Response:
    def __init__(self, text: str) -> None:
        self.output_text = text


class ControlledHandler(ChatHandler):
    def __init__(self, config: Config) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.active = 0
        self.max_active = 0
        super().__init__(config, StubRoleStore())

    def _create_client(self) -> object:
        return object()

    async def _request_ai(self, _prompt: str, history: list[dict[str, str]], *_: Any, **__: Any) -> Response:
        snapshot = [item.copy() for item in history]
        self.calls.append(snapshot)
        message = history[-1]["content"]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            gate = self.gates.get(message)
            if gate:
                await gate.wait()
            if message == "fail":
                raise ValueError("failed")
            if message == "slow":
                await asyncio.sleep(1)
            return Response(f"reply:{message}")
        finally:
            self.active -= 1


class AIChatConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    def make_handler(self, **kwargs: Any) -> ControlledHandler:
        return ControlledHandler(Config(aichat_key="key", aichat_model="model", aichat_memory_enabled=False, **kwargs))

    async def test_same_session_is_serialized_and_ordered(self) -> None:
        handler = self.make_handler()
        handler.gates["first"] = asyncio.Event()
        first = asyncio.create_task(handler.ask("first", "s", "default"))
        await asyncio.sleep(0)
        second = asyncio.create_task(handler.ask("second", "s", "default"))
        await asyncio.sleep(0)
        self.assertEqual(len(handler.calls), 1)
        handler.gates["first"].set()
        self.assertEqual(await asyncio.gather(first, second), ["reply:first", "reply:second"])
        self.assertEqual([item["content"] for item in handler.histories["s"][1:]], ["first", "reply:first", "second", "reply:second"])

    async def test_failure_removes_only_its_own_message(self) -> None:
        handler = self.make_handler()
        first, second = await asyncio.gather(
            handler.ask("fail", "s", "default"),
            handler.ask("ok", "s", "default"),
        )
        self.assertIn("失败", first)
        self.assertEqual(second, "reply:ok")
        self.assertEqual([item["content"] for item in handler.histories["s"][1:]], ["ok", "reply:ok"])

    async def test_reset_during_request_prevents_old_response_writeback(self) -> None:
        handler = self.make_handler()
        handler.gates["first"] = asyncio.Event()
        request = asyncio.create_task(handler.ask("first", "s", "default"))
        await asyncio.sleep(0)
        handler.clear_history("s")
        handler.gates["first"].set()
        self.assertEqual(await request, "reply:first")
        self.assertNotIn("s", handler.histories)

    async def test_global_concurrency_limit_applies_across_sessions(self) -> None:
        handler = self.make_handler(aichat_max_concurrency=2)
        for value in ("a", "b", "c"):
            handler.gates[value] = asyncio.Event()
        tasks = [asyncio.create_task(handler.ask(value, value, "default")) for value in ("a", "b", "c")]
        await asyncio.sleep(0.05)
        self.assertEqual(handler.max_active, 2)
        for gate in handler.gates.values():
            gate.set()
        await asyncio.gather(*tasks)

    async def test_timeout_rolls_back_user_message(self) -> None:
        handler = self.make_handler(aichat_request_timeout_seconds=0.01)
        response = await handler.ask("slow", "s", "default")
        self.assertIn("失败", response)
        self.assertEqual(handler.histories["s"], [{"role": "system", "content": "prompt:default"}])


if __name__ == "__main__":
    unittest.main()
