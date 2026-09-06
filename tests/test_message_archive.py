from __future__ import annotations

import asyncio
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
import src.plugins.message_archive as archive_plugin
from src.plugins.message_archive.store import (
    MESSAGE_ARCHIVE_MIGRATIONS,
    ArchivedGroupMessage,
    MessageArchiveStore,
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

    def test_record_messages_uses_one_batch_and_commit(self) -> None:
        connection = FakeConnection()
        store = MessageArchiveStore(Config(mysql_host="db", mysql_user="u", mysql_password="p"))
        messages = [self._message("1"), self._message("2")]
        with (
            patch("src.plugins.message_archive.store.run_mysql_migrations"),
            patch("src.plugins.message_archive.store.connect_mysql", return_value=connection),
        ):
            store.record_messages(messages)
        self.assertEqual(len(connection.executed), 2)
        self.assertEqual([params[2] for _, params in connection.executed], ["1", "2"])
        self.assertTrue(connection.committed)

    def test_archive_queue_drops_new_record_when_full(self) -> None:
        original_queue = archive_plugin._archive_queue
        original_accepting = archive_plugin._archive_accepting
        archive_plugin._archive_queue = asyncio.Queue(maxsize=1)
        archive_plugin._archive_accepting = True
        try:
            self.assertTrue(archive_plugin._enqueue_archive(self._message("1"), 90))
            self.assertFalse(archive_plugin._enqueue_archive(self._message("2"), 90))
            self.assertEqual(archive_plugin._archive_queue.qsize(), 1)
        finally:
            archive_plugin._archive_queue = original_queue
            archive_plugin._archive_accepting = original_accepting

    @staticmethod
    def _message(message_id: str) -> ArchivedGroupMessage:
        return ArchivedGroupMessage(
            group_id="100", user_id="200", message_id=message_id, bot_id="400",
            sender_nickname="n", sender_card="c", message_type="group", sub_type="normal",
            message_text="text", message_json="[]", segment_types="text",
            content_hash="a" * 64, sent_at=datetime(2026, 1, 1),
        )

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

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        self.executed.extend((sql, item) for item in params)


if __name__ == "__main__":
    unittest.main()
