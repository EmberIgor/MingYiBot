from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import nonebot

nonebot.init()

from src.plugins.ai_chat.config import Config
from src.plugins.ai_chat.data_source import ChatHandler
from src.plugins.ai_chat.memory_store import MemoryStoreError, MySQLMemoryStore


class StubRoleStore:
    def get_prompt(self, role_name: str) -> str:
        return "test prompt"


class AIMemoryStoreTest(unittest.TestCase):
    def test_default_mysql_backend_is_unavailable_without_config(self) -> None:
        handler = ChatHandler(Config(), StubRoleStore())

        self.assertTrue(handler.memory_enabled())
        self.assertEqual(handler._memory_items("user:1"), [])
        with self.assertRaises(MemoryStoreError):
            handler.list_memories("user:1")

    def test_json_backend_keeps_existing_memory_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "memories.json")
            config = Config(aichat_memory_backend="json", aichat_memory_path=path, aichat_memory_max_items=2)
            handler = ChatHandler(config, StubRoleStore())

            first = handler.remember("user:1", "  第一条   记忆  ")
            second = handler.remember("user:1", "第二条记忆")
            third = handler.remember("user:1", "第三条记忆")

            self.assertEqual(first["content"], "第一条 记忆")
            self.assertEqual(second["content"], "第二条记忆")
            self.assertEqual(third["content"], "第三条记忆")
            self.assertEqual(
                [item["content"] for item in handler.list_memories("user:1")],
                ["第二条记忆", "第三条记忆"],
            )

    def test_mysql_content_normalization_matches_json_store(self) -> None:
        store = MySQLMemoryStore.__new__(MySQLMemoryStore)

        content = store._normalize_content("  a\n b\tc  " + "x" * 200)

        self.assertEqual(content, ("a b c " + "x" * 200)[:160].strip())


if __name__ == "__main__":
    unittest.main()
