from __future__ import annotations

import unittest
import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import patch

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

import src.plugins.message_archive as message_archive
from src.plugins.message_archive.config import Config
from src.plugins.message_archive.store import (
    MESSAGE_ARCHIVE_MIGRATIONS,
    ArchivedGroupMessage,
    GroupMessageStats,
    MessageArchiveStore,
    UserMessageCount,
    extract_keywords,
)


class MessageArchiveStoreTest(unittest.TestCase):
    def test_message_archive_migration_shape(self) -> None:
        migration_sql = "\n".join(
            statement
            for migration in MESSAGE_ARCHIVE_MIGRATIONS
            for statement in migration.statements
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS group_message_records", migration_sql)
        self.assertIn("group_id VARCHAR(64) NOT NULL", migration_sql)
        self.assertIn("message_id VARCHAR(128) NOT NULL", migration_sql)
        self.assertIn("message_json MEDIUMTEXT NOT NULL", migration_sql)
        self.assertIn("UNIQUE KEY uniq_group_message", migration_sql)
        self.assertIn("KEY idx_group_sent_at", migration_sql)
        self.assertIn("KEY idx_group_user_sent_at", migration_sql)

    def test_record_message_runs_migration_and_upserts(self) -> None:
        connection = FakeConnection()
        store = MessageArchiveStore(
            Config(
                mysql_host="db",
                mysql_user="mingyi",
                mysql_password="pw",
                mysql_database="mingyibot",
            )
        )
        message = ArchivedGroupMessage(
            group_id="100",
            user_id="200",
            message_id="300",
            bot_id="400",
            sender_nickname="茗懿",
            sender_card="群名片",
            message_type="group",
            sub_type="normal",
            message_text="今晚跑团吗",
            message_json='[{"type":"text","data":{"text":"今晚跑团吗"}}]',
            segment_types="text",
            content_hash="a" * 64,
            sent_at=datetime(2026, 1, 1, 12, 0, 0),
        )

        with (
            patch("src.plugins.message_archive.store.run_mysql_migrations") as run_migrations,
            patch("src.plugins.message_archive.store.connect_mysql", return_value=connection),
        ):
            store.record_message(message)

        run_migrations.assert_called_once()
        self.assertTrue(connection.committed)
        self.assertEqual(connection.executed[0][1][0], "100")
        self.assertEqual(connection.executed[0][1][1], "200")
        self.assertEqual(connection.executed[0][1][2], "300")
        self.assertIn("ON DUPLICATE KEY UPDATE", connection.executed[0][0])

    def test_extract_keywords_skips_commands_and_counts_tokens(self) -> None:
        keywords = extract_keywords(
            [
                ".群统计 今日",
                "跑团 跑团 python bot python",
                "https://example.com 跑团",
            ],
            limit=3,
        )

        self.assertEqual(keywords[0].keyword, "跑团")
        self.assertEqual(keywords[0].count, 3)
        self.assertEqual(keywords[1].keyword, "python")
        self.assertEqual(keywords[1].count, 2)


class MessageArchiveCommandTest(unittest.TestCase):
    def test_parse_private_group_query_requires_group_id(self) -> None:
        self.assertEqual(message_archive._parse_private_group_query("123456 今日"), (123456, "今日"))
        self.assertEqual(message_archive._parse_private_group_query("群号：123456 30天"), (123456, "30天"))
        self.assertIsNone(message_archive._parse_private_group_query(""))
        self.assertIsNone(message_archive._parse_private_group_query("今日"))

    def test_format_private_group_stats_response_uses_target_group(self) -> None:
        fake_settings = FakeRuntimeSettings(enabled=True)
        fake_store = FakeArchiveStore()
        original_settings = message_archive.runtime_settings
        original_store = message_archive.archive_store
        message_archive.runtime_settings = fake_settings
        message_archive.archive_store = fake_store
        try:
            response = asyncio.run(
                message_archive._format_group_stats_response(
                    123456,
                    "今日",
                    group_label="群 123456 ",
                )
            )
        finally:
            message_archive.runtime_settings = original_settings
            message_archive.archive_store = original_store

        self.assertIn("群 123456 今日统计：", response)
        self.assertIn("消息：3 条", response)
        self.assertIn("活跃用户：2 人", response)
        self.assertIn("Alice(200)：2 条", response)
        self.assertEqual(fake_settings.group_ids, [123456])
        self.assertEqual(fake_store.summary_calls[0][0], 123456)

    def test_format_private_group_hotwords_response_uses_target_group(self) -> None:
        fake_settings = FakeRuntimeSettings(enabled=True)
        fake_store = FakeArchiveStore()
        original_settings = message_archive.runtime_settings
        original_store = message_archive.archive_store
        message_archive.runtime_settings = fake_settings
        message_archive.archive_store = fake_store
        try:
            response = asyncio.run(
                message_archive._format_group_hotwords_response(
                    123456,
                    "7天",
                    group_label="群 123456 ",
                )
            )
        finally:
            message_archive.runtime_settings = original_settings
            message_archive.archive_store = original_store

        self.assertIn("群 123456 近7天热词：", response)
        self.assertIn("1. 跑团：2", response)
        self.assertEqual(fake_settings.group_ids, [123456])
        self.assertEqual(fake_store.recent_text_calls[0][0], 123456)


class FakeRuntimeSettings:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.group_ids: list[int | None] = []

    async def get_bool_async(self, *_: Any, group_id: int | None = None) -> bool:
        self.group_ids.append(group_id)
        return self.enabled


class FakeArchiveStore:
    def __init__(self) -> None:
        self.summary_calls: list[tuple[int, datetime]] = []
        self.top_user_calls: list[tuple[int, datetime, int]] = []
        self.recent_text_calls: list[tuple[int, datetime, int]] = []

    async def summarize_group_async(self, group_id: int, since: datetime) -> GroupMessageStats:
        self.summary_calls.append((group_id, since))
        return GroupMessageStats(
            message_count=3,
            active_user_count=2,
            first_sent_at=datetime(2026, 1, 1, 0, 0, 0),
            last_sent_at=datetime(2026, 1, 1, 1, 0, 0),
        )

    async def top_users_async(self, group_id: int, since: datetime, *, limit: int = 5) -> list[UserMessageCount]:
        self.top_user_calls.append((group_id, since, limit))
        return [UserMessageCount(user_id="200", display_name="Alice", message_count=2)]

    async def recent_texts_async(self, group_id: int, since: datetime, *, limit: int) -> list[str]:
        self.recent_text_calls.append((group_id, since, limit))
        return ["跑团 跑团 python"]


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
        self.rowcount = 1

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))


if __name__ == "__main__":
    unittest.main()
