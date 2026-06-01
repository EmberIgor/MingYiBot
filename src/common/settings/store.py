from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Literal

from nonebot import get_plugin_config, logger
from src.common.db import DatabaseError, MySQLMigration, connect_mysql, run_mysql_migrations

from .config import RuntimeSettingsConfig

ScopeType = Literal["global", "group", "user"]
ValueType = Literal["bool", "int", "str", "list"]


class SettingsStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class SettingDefinition:
    namespace: str
    key: str
    value_type: ValueType
    label: str
    min_value: int | None = None
    max_value: int | None = None


RUNTIME_SETTINGS_MIGRATIONS = (
    MySQLMigration(
        version=1,
        name="create_runtime_settings",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS runtime_settings (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              scope_type VARCHAR(16) NOT NULL,
              scope_id VARCHAR(64) NOT NULL DEFAULT '',
              namespace VARCHAR(64) NOT NULL,
              setting_key VARCHAR(64) NOT NULL,
              value_json TEXT NOT NULL,
              updated_by VARCHAR(64) NOT NULL DEFAULT '',
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uniq_runtime_setting (scope_type, scope_id, namespace, setting_key),
              KEY idx_runtime_scope (scope_type, scope_id),
              KEY idx_runtime_namespace (namespace, setting_key)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """,
        ),
    ),
)


SETTING_DEFINITIONS: dict[tuple[str, str], SettingDefinition] = {
    ("daily_news", "enabled"): SettingDefinition("daily_news", "enabled", "bool", "每日新闻"),
    ("sunset", "default_city"): SettingDefinition("sunset", "default_city", "str", "火烧云城市"),
    ("ai_chat", "web_search"): SettingDefinition("ai_chat", "web_search", "bool", "AI联网"),
    ("ai_chat", "default_role"): SettingDefinition("ai_chat", "default_role", "str", "默认角色"),
    ("repeater", "threshold"): SettingDefinition(
        "repeater",
        "threshold",
        "int",
        "复读阈值",
        min_value=0,
        max_value=20,
    ),
    ("message_archive", "enabled"): SettingDefinition("message_archive", "enabled", "bool", "群消息记录"),
    ("message_archive", "retention_days"): SettingDefinition(
        "message_archive",
        "retention_days",
        "int",
        "群消息记录保留天数",
        min_value=1,
        max_value=3650,
    ),
}

_store: RuntimeSettingsStore | None = None


class RuntimeSettingsStore:
    def __init__(
        self,
        config: RuntimeSettingsConfig,
        *,
        cache_ttl_seconds: int | None = None,
    ) -> None:
        self.config = config
        if cache_ttl_seconds is None:
            cache_ttl_seconds = config.runtime_settings_cache_seconds
        self.cache_ttl_seconds = max(int(cache_ttl_seconds), 0)
        self._schema_ready = False
        self._cache: dict[tuple[str, str, tuple[tuple[ScopeType, str], ...]], tuple[float, Any]] = {}

    def get_bool(
        self,
        namespace: str,
        key: str,
        default: bool,
        *,
        group_id: int | str | None = None,
        user_id: int | str | None = None,
    ) -> bool:
        return bool(self.get_value(namespace, key, default, group_id=group_id, user_id=user_id))

    def get_int(
        self,
        namespace: str,
        key: str,
        default: int,
        *,
        group_id: int | str | None = None,
        user_id: int | str | None = None,
    ) -> int:
        return int(self.get_value(namespace, key, default, group_id=group_id, user_id=user_id))

    def get_str(
        self,
        namespace: str,
        key: str,
        default: str,
        *,
        group_id: int | str | None = None,
        user_id: int | str | None = None,
    ) -> str:
        return str(self.get_value(namespace, key, default, group_id=group_id, user_id=user_id))

    def get_list(
        self,
        namespace: str,
        key: str,
        default: list[Any],
        *,
        group_id: int | str | None = None,
        user_id: int | str | None = None,
    ) -> list[Any]:
        value = self.get_value(namespace, key, default, group_id=group_id, user_id=user_id)
        return value if isinstance(value, list) else default

    def get_value(
        self,
        namespace: str,
        key: str,
        default: Any,
        *,
        group_id: int | str | None = None,
        user_id: int | str | None = None,
    ) -> Any:
        definition = self._definition(namespace, key)
        scopes = self._lookup_scopes(group_id=group_id, user_id=user_id)
        cache_key = (definition.namespace, definition.key, tuple(scopes))
        cached = self._cache.get(cache_key)
        if cached and cached[0] >= time.monotonic():
            return cached[1]

        try:
            value = self._fetch_value(definition, scopes)
        except Exception as exc:
            error = self._settings_error(exc)
            logger.warning("Runtime setting lookup skipped for {}.{}: {}", namespace, key, error)
            self._cache[cache_key] = (time.monotonic() + self.cache_ttl_seconds, default)
            return default

        if value is None:
            value = default
        self._cache[cache_key] = (time.monotonic() + self.cache_ttl_seconds, value)
        return value

    async def get_bool_async(self, *args: Any, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self.get_bool, *args, **kwargs)

    async def get_int_async(self, *args: Any, **kwargs: Any) -> int:
        return await asyncio.to_thread(self.get_int, *args, **kwargs)

    async def get_str_async(self, *args: Any, **kwargs: Any) -> str:
        return await asyncio.to_thread(self.get_str, *args, **kwargs)

    async def get_list_async(self, *args: Any, **kwargs: Any) -> list[Any]:
        return await asyncio.to_thread(self.get_list, *args, **kwargs)

    def set_value(
        self,
        scope_type: ScopeType,
        scope_id: int | str | None,
        namespace: str,
        key: str,
        value: Any,
        *,
        updated_by: int | str,
    ) -> Any:
        definition = self._definition(namespace, key)
        normalized_scope_type, normalized_scope_id = self._normalize_scope(scope_type, scope_id)
        coerced_value = self._coerce_value(definition, value)
        value_json = json.dumps(coerced_value, ensure_ascii=False)

        try:
            self._ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO runtime_settings
                            (scope_type, scope_id, namespace, setting_key, value_json, updated_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            value_json = VALUES(value_json),
                            updated_by = VALUES(updated_by),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            normalized_scope_type,
                            normalized_scope_id,
                            definition.namespace,
                            definition.key,
                            value_json,
                            str(updated_by).strip(),
                        ),
                    )
                connection.commit()
        except Exception as exc:
            raise self._settings_error(exc) from exc

        self._cache.clear()
        return coerced_value

    async def set_value_async(self, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self.set_value, *args, **kwargs)

    def delete_value(
        self,
        scope_type: ScopeType,
        scope_id: int | str | None,
        namespace: str,
        key: str,
    ) -> bool:
        definition = self._definition(namespace, key)
        normalized_scope_type, normalized_scope_id = self._normalize_scope(scope_type, scope_id)

        try:
            self._ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM runtime_settings
                        WHERE scope_type = %s
                          AND scope_id = %s
                          AND namespace = %s
                          AND setting_key = %s
                        """,
                        (
                            normalized_scope_type,
                            normalized_scope_id,
                            definition.namespace,
                            definition.key,
                        ),
                    )
                    deleted = cursor.rowcount > 0
                connection.commit()
        except Exception as exc:
            raise self._settings_error(exc) from exc

        self._cache.clear()
        return deleted

    async def delete_value_async(self, *args: Any, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self.delete_value, *args, **kwargs)

    def list_scope_values(self, scope_type: ScopeType, scope_id: int | str | None) -> dict[tuple[str, str], Any]:
        normalized_scope_type, normalized_scope_id = self._normalize_scope(scope_type, scope_id)
        try:
            self._ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT namespace, setting_key, value_json
                        FROM runtime_settings
                        WHERE scope_type = %s AND scope_id = %s
                        """,
                        (normalized_scope_type, normalized_scope_id),
                    )
                    rows = cursor.fetchall()
        except Exception as exc:
            raise self._settings_error(exc) from exc

        values: dict[tuple[str, str], Any] = {}
        for namespace, setting_key, value_json in rows:
            definition = SETTING_DEFINITIONS.get((str(namespace), str(setting_key)))
            if definition is None:
                continue
            values[(definition.namespace, definition.key)] = self._decode_value(definition, str(value_json))
        return values

    async def list_scope_values_async(self, *args: Any, **kwargs: Any) -> dict[tuple[str, str], Any]:
        return await asyncio.to_thread(self.list_scope_values, *args, **kwargs)

    def _fetch_value(
        self,
        definition: SettingDefinition,
        scopes: list[tuple[ScopeType, str]],
    ) -> Any | None:
        self._ensure_schema()
        with connect_mysql(self.config) as connection:
            with connection.cursor() as cursor:
                for scope_type, scope_id in scopes:
                    cursor.execute(
                        """
                        SELECT value_json
                        FROM runtime_settings
                        WHERE scope_type = %s
                          AND scope_id = %s
                          AND namespace = %s
                          AND setting_key = %s
                        LIMIT 1
                        """,
                        (scope_type, scope_id, definition.namespace, definition.key),
                    )
                    row = cursor.fetchone()
                    if row:
                        return self._decode_value(definition, str(row[0]))
        return None

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        try:
            run_mysql_migrations(
                self.config,
                namespace="runtime_settings",
                migrations=RUNTIME_SETTINGS_MIGRATIONS,
            )
        except Exception as exc:
            raise self._settings_error(exc) from exc
        self._schema_ready = True

    def _decode_value(self, definition: SettingDefinition, value_json: str) -> Any:
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError as exc:
            raise SettingsStoreError(f"运行时配置 JSON 无效：{definition.namespace}.{definition.key}") from exc
        return self._coerce_value(definition, value)

    def _coerce_value(self, definition: SettingDefinition, value: Any) -> Any:
        if definition.value_type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in {"开", "开启", "true", "1", "yes", "on"}:
                return True
            if isinstance(value, str) and value.strip().lower() in {"关", "关闭", "false", "0", "no", "off"}:
                return False
            raise SettingsStoreError(f"{definition.label} 必须是开或关。")

        if definition.value_type == "int":
            try:
                int_value = int(value)
            except (TypeError, ValueError) as exc:
                raise SettingsStoreError(f"{definition.label} 必须是数字。") from exc
            if definition.min_value is not None and int_value < definition.min_value:
                raise SettingsStoreError(f"{definition.label} 不能小于 {definition.min_value}。")
            if definition.max_value is not None and int_value > definition.max_value:
                raise SettingsStoreError(f"{definition.label} 不能大于 {definition.max_value}。")
            return int_value

        if definition.value_type == "str":
            text = str(value).strip()
            if not text:
                raise SettingsStoreError(f"{definition.label} 不能为空。")
            return text[:128]

        if definition.value_type == "list":
            if not isinstance(value, list):
                raise SettingsStoreError(f"{definition.label} 必须是列表。")
            return value

        raise SettingsStoreError(f"未知配置类型：{definition.value_type}")

    def _lookup_scopes(
        self,
        *,
        group_id: int | str | None,
        user_id: int | str | None,
    ) -> list[tuple[ScopeType, str]]:
        scopes: list[tuple[ScopeType, str]] = []
        if user_id is not None and str(user_id).strip():
            scopes.append(("user", str(user_id).strip()))
        if group_id is not None and str(group_id).strip():
            scopes.append(("group", str(group_id).strip()))
        scopes.append(("global", ""))
        return scopes

    def _normalize_scope(self, scope_type: ScopeType, scope_id: int | str | None) -> tuple[ScopeType, str]:
        if scope_type not in {"global", "group", "user"}:
            raise SettingsStoreError("配置作用域必须是 global、group 或 user。")
        if scope_type == "global":
            return scope_type, ""

        normalized_scope_id = str(scope_id or "").strip()
        if not normalized_scope_id:
            raise SettingsStoreError("群/用户配置必须指定作用域 ID。")
        return scope_type, normalized_scope_id

    def _definition(self, namespace: str, key: str) -> SettingDefinition:
        definition = SETTING_DEFINITIONS.get((namespace, key))
        if definition is None:
            raise SettingsStoreError(f"不允许写入配置：{namespace}.{key}")
        return definition

    def _settings_error(self, exc: Exception) -> SettingsStoreError:
        if isinstance(exc, SettingsStoreError):
            return exc
        if isinstance(exc, DatabaseError):
            return SettingsStoreError(str(exc))
        return SettingsStoreError(str(exc))


def get_runtime_settings_store() -> RuntimeSettingsStore:
    global _store
    if _store is None:
        _store = RuntimeSettingsStore(get_plugin_config(RuntimeSettingsConfig))
    return _store


def reset_runtime_settings_store(store: RuntimeSettingsStore | None = None) -> None:
    global _store
    _store = store
