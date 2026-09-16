from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plugins.ai_chat.memory_store import AI_CHAT_MEMORY_MIGRATIONS, MemoryStore, MySQLMemoryStore


class LegacyMemoryBackupTest(unittest.TestCase):
    def test_existing_json_backup_can_still_be_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "memories.json")
            store = MemoryStore(path, max_items=2)
            store.add_memory("user:1", "第一条")
            store.add_memory("user:1", "第二条")
            store.add_memory("user:1", "第三条")
            self.assertEqual(
                [item["content"] for item in MemoryStore(path, max_items=2).list_memories("user:1")],
                ["第二条", "第三条"],
            )

    def test_legacy_database_schema_remains_available_for_backup(self) -> None:
        migration_sql = "\n".join(
            statement for migration in AI_CHAT_MEMORY_MIGRATIONS for statement in migration.statements
        )
        self.assertIn("CREATE TABLE IF NOT EXISTS ai_chat_memories", migration_sql)
        self.assertIn("ADD COLUMN source", migration_sql)
        self.assertIn("ADD COLUMN last_used_at", migration_sql)

    def test_legacy_mysql_normalization_is_preserved(self) -> None:
        store = MySQLMemoryStore.__new__(MySQLMemoryStore)
        self.assertEqual(store._normalize_content("  a\n b\tc  "), "a b c")


if __name__ == "__main__":
    unittest.main()
