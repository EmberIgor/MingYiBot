from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any
from unittest.mock import patch

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from src.plugins.message_archive.config import Config
from src.plugins.message_archive.store import (
    MESSAGE_ARCHIVE_MIGRATIONS,
    ArchivedGroupMessage,
    MessageArchiveStore,
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
