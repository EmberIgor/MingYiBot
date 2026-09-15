"""Opt-in real database tests. Never point these at a production database."""
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from src.common.db.config import MySQLConfig
from src.common.db.mysql import connect_mysql
from src.common.db.postgres import connect_postgres, run_postgres_migrations
from src.common.db.migrate import migrate, read_config, TABLES
from src.common.settings.config import RuntimeSettingsConfig
from src.common.settings.store import RuntimeSettingsStore
from src.plugins.ai_chat.memory_store import MySQLMemoryStore
from src.plugins.message_archive.config import Config as ArchiveConfig
from src.plugins.message_archive.store import MessageArchiveStore, ArchivedGroupMessage


@unittest.skipUnless(os.getenv("INTEGRATION_DB") == "1", "requires dedicated MySQL/PG test databases")
class DatabaseIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = (read_config(os.environ["INTEGRATION_ENV"]) if os.getenv("INTEGRATION_ENV") else
                      MySQLConfig(**{k.lower(): v for k, v in os.environ.items()}))
        for name in (cls.config.mysql_database, cls.config.postgres_database):
            if not name.startswith("mingyibot_test"):
                raise RuntimeError("Integration databases must start with mingyibot_test")

    def stores(self, backend):
        values = self.config.model_dump() | {"db_backend": backend}
        memory = MySQLMemoryStore(
            **{key: getattr(self.config, f"{backend}_{key}") for key in
               ("host", "port", "database", "user", "password", "connect_timeout_seconds")},
            backend=backend, max_items=2,
        )
        return (memory, MessageArchiveStore(ArchiveConfig(**values)),
                RuntimeSettingsStore(RuntimeSettingsConfig(**values), cache_ttl_seconds=0))

    def clear(self, backend):
        memory, archive, settings = self.stores(backend)
        archive.ensure_schema()
        settings._ensure_schema()
        connect = connect_postgres if backend == "postgres" else connect_mysql
        with connect(self.config) as connection:
            with connection.cursor() as cursor:
                for table in TABLES:
                    cursor.execute(f"DELETE FROM {table}")
            connection.commit()
        return memory, archive, settings

    def test_backends_and_full_migration(self):
        for backend in ("mysql", "postgres"):
            with self.subTest(backend=backend):
                memory, archive, settings = self.clear(backend)
                first = memory.add_memory("user:42", "喜欢喝乌龙茶🍵")
                duplicate = memory.add_memory("user:42", "喜欢喝乌龙茶🍵")
                self.assertEqual(first["id"], duplicate["id"])
                memory.add_memory("user:42", "住在香港")
                memory.add_memory("user:42", "职业是程序员")
                self.assertEqual(len(memory.list_memories("user:42")), 2)
                memory.replace_memories("user:42", ["喜欢围棋", "养猫"])
                self.assertEqual(len(memory.list_memories("user:42")), 2)
                self.assertTrue(memory.delete_memory("user:42", memory.list_memories("user:42")[0]["id"]))
                memory.compact_memories("user:42")
                message = ArchivedGroupMessage(
                    "100", "200", "300", "400", "昵称😀", "群\x00名片😀", "group", "normal",
                    "换行\n引号'和\\反斜杠", '[ {"type": "text", "data": {"text": "😀"}} ]',
                    "text", "a" * 64, datetime(2026, 1, 1, 12, 30),
                )
                archive.record_messages([message, replace(message, message_text="更新消息😀")])
                settings.set_value("group", 100, "daily_news", "enabled", True, updated_by=200)
                self.assertTrue(settings.get_bool("daily_news", "enabled", False, group_id=100))
                settings.set_value("group", 100, "daily_news", "enabled", False, updated_by=200)
                self.assertFalse(settings.get_bool("daily_news", "enabled", True, group_id=100))
                self.assertTrue(settings.delete_value("group", 100, "daily_news", "enabled"))
                settings.set_value("global", None, "ai_chat", "default_role", "测试角色", updated_by=200)
                connect = connect_postgres if backend == "postgres" else connect_mysql
                with connect(self.config) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT COUNT(*), MIN(message_text) FROM group_message_records")
                        self.assertEqual(cursor.fetchone(), (1, "更新消息😀"))
                        cursor.execute("UPDATE ai_chat_memories SET is_archived=1, last_used_at=NULL")
                    connection.commit()
                self.assertEqual(memory.list_memories("user:42"), [])
                self.stores(backend)  # Schema initialization is repeatable.

        self.clear("postgres")
        with tempfile.TemporaryDirectory() as directory:
            backup = str(Path(directory) / "snapshot.jsonl.gz")
            report = migrate(self.config, "import", backup_path=backup)
            self.assertEqual(report, migrate(self.config, "verify"))
            self.assertGreater(Path(backup).stat().st_size, 0)
            with self.assertRaises(ValueError):
                migrate(self.config, "import", backup_path=str(Path(directory) / "second.gz"))
            # Refusing a second import must not alter any target values.
            self.assertEqual(report, migrate(self.config, "verify"))
            memory, archive, _ = self.stores("postgres")
            with connect_postgres(self.config) as connection:
                old_max = connection.execute("SELECT MAX(id) FROM ai_chat_memories").fetchone()[0]
            item = memory.add_memory("user:new", "全新的记忆")
            self.assertGreater(int(item["id"]), old_max)
            self.assertEqual(archive.prune_group_before(100, datetime(2027, 1, 1)), 1)

            # A constraint failure in the second table rolls back the first table too.
            self.clear("postgres")
            with connect_postgres(self.config) as connection:
                connection.execute("ALTER TABLE group_message_records ADD CONSTRAINT reject_fixture CHECK (group_id <> '100')")
            try:
                with self.assertRaises(Exception):
                    migrate(self.config, "import", backup_path=str(Path(directory) / "failed.gz"))
                with connect_postgres(self.config) as connection:
                    for table in TABLES:
                        self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            finally:
                with connect_postgres(self.config) as connection:
                    connection.execute("ALTER TABLE group_message_records DROP CONSTRAINT reject_fixture")
