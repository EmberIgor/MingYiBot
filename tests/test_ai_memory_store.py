from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

import nonebot

nonebot.init()

from src.common.db import MySQLConfig, missing_mysql_config_keys
from src.plugins.ai_chat.config import Config
from src.plugins.ai_chat.data_source import ChatHandler
from src.plugins.ai_chat.memory_store import (
    AI_CHAT_MEMORY_MIGRATIONS,
    MemoryStoreError,
    MySQLMemoryStore,
)


class StubRoleStore:
    def get_prompt(self, role_name: str) -> str:
        return "test prompt"


class FakeAIResponse:
    output_text = "ok"


class RecordingChatHandler(ChatHandler):
    def __init__(self, config: Config, role_store: StubRoleStore) -> None:
        self.recorded_web_search: bool | None = None
        super().__init__(config, role_store)

    def _create_client(self) -> object:
        return object()

    async def _request_ai(self, *args: Any, web_search: bool | None = None, **kwargs: Any) -> Any:
        self.recorded_web_search = web_search
        return FakeAIResponse()


class AIMemoryStoreTest(unittest.TestCase):
    def test_default_mysql_backend_is_unavailable_without_config(self) -> None:
        handler = ChatHandler(Config(), StubRoleStore())

        self.assertTrue(handler.memory_enabled())
        self.assertEqual(asyncio.run(handler._memory_items("user:1")), [])
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

    def test_ask_accepts_runtime_web_search_override(self) -> None:
        config = Config(
            aichat_memory_enabled=False,
            aichat_key="key",
            aichat_model="model",
            aichat_web_search=False,
        )
        handler = RecordingChatHandler(config, StubRoleStore())

        response = asyncio.run(handler.ask("hello", "session:1", "default", web_search=True))

        self.assertEqual(response, "ok")
        self.assertTrue(handler.recorded_web_search)

    def test_mysql_content_normalization_matches_json_store(self) -> None:
        store = MySQLMemoryStore.__new__(MySQLMemoryStore)

        content = store._normalize_content("  a\n b\tc  " + "x" * 200)

        self.assertEqual(content, ("a b c " + "x" * 200)[:160].strip())

    def test_mysql_config_missing_keys_are_shared(self) -> None:
        self.assertEqual(
            missing_mysql_config_keys(MySQLConfig(mysql_host="db", mysql_user="mingyi")),
            ["MYSQL_PASSWORD"],
        )

    def test_mysql_memory_migrations_add_metadata_columns(self) -> None:
        migration_sql = "\n".join(
            statement
            for migration in AI_CHAT_MEMORY_MIGRATIONS
            for statement in migration.statements
        )

        self.assertEqual([migration.version for migration in AI_CHAT_MEMORY_MIGRATIONS], [1, 2])
        self.assertIn("ADD COLUMN source", migration_sql)
        self.assertIn("ADD COLUMN category", migration_sql)
        self.assertIn("ADD COLUMN confidence", migration_sql)
        self.assertIn("ADD COLUMN last_used_at", migration_sql)
        self.assertIn("ADD COLUMN is_archived", migration_sql)

    def test_mysql_add_memory_uses_upsert_and_metadata_defaults(self) -> None:
        store = MySQLMemoryStore.__new__(MySQLMemoryStore)
        store.max_items = 20
        connection = FakeConnection()
        store._connect = lambda: connection

        item = store.add_memory(
            "user:1",
            "  hello\nworld  ",
            source="AI Summary",
            category="Profile",
            confidence=2.0,
        )

        insert_sql, insert_params = connection.executed[0]
        self.assertIn("ON DUPLICATE KEY UPDATE", insert_sql)
        self.assertEqual(insert_params[0], "user:1")
        self.assertEqual(insert_params[1], "hello world")
        self.assertEqual(insert_params[3], "ai_summary")
        self.assertEqual(insert_params[4], "profile")
        self.assertEqual(insert_params[5], 1.0)
        self.assertEqual(item["id"], "42")
        self.assertTrue(connection.committed)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.executed = self.cursor_obj.executed
        self.committed = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def cursor(self, **_: Any) -> "FakeCursor":
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.lastrowid = 42
        self.rowcount = 0
        self._next_fetchone: Any = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))
        if "SELECT COUNT(*)" in sql:
            self._next_fetchone = (1,)
        elif "SELECT id, content, created_at, updated_at" in sql:
            self._next_fetchone = {
                "id": 42,
                "content": "hello world",
                "created_at": datetime(2026, 1, 1, 0, 0, 0),
                "updated_at": datetime(2026, 1, 1, 0, 0, 0),
            }

    def fetchone(self) -> Any:
        value = self._next_fetchone
        self._next_fetchone = None
        return value


if __name__ == "__main__":
    unittest.main()
