from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from src.common.settings import RUNTIME_SETTINGS_MIGRATIONS, RuntimeSettingsConfig, RuntimeSettingsStore
from src.common.settings.store import SettingsStoreError


class RuntimeSettingsStoreTest(unittest.TestCase):
    def test_runtime_settings_migration_shape(self) -> None:
        migration_sql = "\n".join(
            statement
            for migration in RUNTIME_SETTINGS_MIGRATIONS
            for statement in migration.statements
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS runtime_settings", migration_sql)
        self.assertIn("scope_type", migration_sql)
        self.assertIn("scope_id", migration_sql)
        self.assertIn("namespace", migration_sql)
        self.assertIn("setting_key", migration_sql)
        self.assertIn("value_json TEXT NOT NULL", migration_sql)
        self.assertIn("updated_by", migration_sql)
        self.assertIn("UNIQUE KEY uniq_runtime_setting", migration_sql)

    def test_group_and_user_overrides_take_precedence(self) -> None:
        store = InMemorySettingsStore()
        store.values[("global", "", "ai_chat", "default_role")] = json.dumps("assistant")
        store.values[("group", "100", "ai_chat", "default_role")] = json.dumps("creative")
        store.values[("user", "200", "ai_chat", "default_role")] = json.dumps("jarvis")

        self.assertEqual(
            store.get_str("ai_chat", "default_role", "default", group_id=100),
            "creative",
        )
        self.assertEqual(
            store.get_str("ai_chat", "default_role", "default", group_id=100, user_id=200),
            "jarvis",
        )

    def test_unconfigured_setting_returns_default(self) -> None:
        store = InMemorySettingsStore()

        self.assertTrue(store.get_bool("daily_news", "enabled", True, group_id=100))

    def test_database_unavailable_falls_back_to_default(self) -> None:
        store = FailingSettingsStore()

        self.assertFalse(store.get_bool("ai_chat", "web_search", False, group_id=100))

    def test_non_whitelisted_key_is_rejected(self) -> None:
        store = InMemorySettingsStore()

        with self.assertRaises(SettingsStoreError):
            store.set_value("group", 100, "ai_chat", "api_key", "secret", updated_by=1)

    def test_set_value_serializes_json_and_invalidates_cache(self) -> None:
        connection = FakeConnection()
        store = RuntimeSettingsStore(
            RuntimeSettingsConfig(
                mysql_host="db",
                mysql_user="mingyi",
                mysql_password="pw",
                mysql_database="mingyibot",
            ),
            cache_ttl_seconds=30,
        )
        store._cache[("daily_news", "enabled", (("group", "100"), ("global", "")))] = (999999, False)

        with (
            patch("src.common.settings.store.connect_mysql", return_value=connection),
            patch("src.common.settings.store.run_mysql_migrations"),
        ):
            value = store.set_value("group", 100, "daily_news", "enabled", True, updated_by=123)

        self.assertTrue(value)
        self.assertEqual(connection.executed[0][1][0], "group")
        self.assertEqual(connection.executed[0][1][1], "100")
        self.assertEqual(connection.executed[0][1][2], "daily_news")
        self.assertEqual(connection.executed[0][1][3], "enabled")
        self.assertEqual(json.loads(connection.executed[0][1][4]), True)
        self.assertEqual(connection.executed[0][1][5], "123")
        self.assertTrue(connection.committed)
        self.assertEqual(store._cache, {})


class InMemorySettingsStore(RuntimeSettingsStore):
    def __init__(self) -> None:
        super().__init__(RuntimeSettingsConfig(), cache_ttl_seconds=0)
        self.values: dict[tuple[str, str, str, str], str] = {}

    def _ensure_schema(self) -> None:
        return None

    def _fetch_value(self, definition, scopes):  # type: ignore[no-untyped-def]
        for scope_type, scope_id in scopes:
            value = self.values.get((scope_type, scope_id, definition.namespace, definition.key))
            if value is not None:
                return self._decode_value(definition, value)
        return None


class FailingSettingsStore(RuntimeSettingsStore):
    def __init__(self) -> None:
        super().__init__(RuntimeSettingsConfig(), cache_ttl_seconds=0)

    def _fetch_value(self, definition, scopes):  # type: ignore[no-untyped-def]
        raise SettingsStoreError("database offline")


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.executed = self.cursor_obj.executed
        self.committed = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def cursor(self) -> "FakeCursor":
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
