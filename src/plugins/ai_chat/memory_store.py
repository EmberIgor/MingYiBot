from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.db import (
    MySQLConnectionSettings,
    MySQLMigration,
    connect_mysql,
    run_mysql_migrations,
)


class MemoryStoreError(RuntimeError):
    pass


AI_CHAT_MEMORY_MIGRATIONS = (
    MySQLMigration(
        version=1,
        name="create_ai_chat_memories",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS ai_chat_memories (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              scope VARCHAR(128) NOT NULL,
              content VARCHAR(255) NOT NULL,
              content_hash CHAR(64) NOT NULL,
              created_at DATETIME NOT NULL,
              updated_at DATETIME NOT NULL,
              UNIQUE KEY uniq_scope_content (scope, content_hash),
              KEY idx_scope_updated (scope, updated_at),
              KEY idx_scope_id (scope, id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """,
        ),
    ),
    MySQLMigration(
        version=2,
        name="add_ai_chat_memory_metadata",
        statements=(
            """
            ALTER TABLE ai_chat_memories
              ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'manual' AFTER content_hash,
              ADD COLUMN category VARCHAR(32) NOT NULL DEFAULT 'general' AFTER source,
              ADD COLUMN confidence DECIMAL(4,3) NOT NULL DEFAULT 1.000 AFTER category,
              ADD COLUMN last_used_at DATETIME NULL AFTER updated_at,
              ADD COLUMN is_archived TINYINT(1) NOT NULL DEFAULT 0 AFTER last_used_at,
              ADD KEY idx_scope_archived_updated (scope, is_archived, updated_at),
              ADD KEY idx_scope_last_used (scope, last_used_at)
            """,
        ),
    ),
)


class MemoryStore:
    def __init__(self, path: str, max_items: int = 20) -> None:
        self.path = Path(path)
        self.max_items = max(max_items, 1)

    def list_memories(self, scope: str) -> list[dict[str, str]]:
        data = self._load()
        users = data.get("users", {})
        memories = users.get(scope, []) if isinstance(users, dict) else []
        if not isinstance(memories, list):
            return []

        return [
            {
                "id": str(item.get("id", "")),
                "content": str(item.get("content", "")),
                "created_at": str(item.get("created_at", "")),
                "updated_at": str(item.get("updated_at", "")),
            }
            for item in memories
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ]

    def add_memory(self, scope: str, content: str, **_: Any) -> dict[str, str] | None:
        normalized_content = self._normalize_content(content)
        if not normalized_content:
            return None

        data = self._load()
        users = self._users(data)
        memories = self._scope_memories(users, scope)
        now = self._now()

        for item in list(memories):
            if self._normalize_content(str(item.get("content", ""))) == normalized_content:
                item["content"] = normalized_content
                item["updated_at"] = now
                memories.remove(item)
                memories.append(item)
                self._trim(memories)
                self._save(data)
                return self._public_item(item)

        item = {
            "id": self._next_id(memories),
            "content": normalized_content,
            "created_at": now,
            "updated_at": now,
        }
        memories.append(item)
        self._trim(memories)
        self._save(data)
        return self._public_item(item)

    def delete_memory(self, scope: str, memory_id: str) -> bool:
        data = self._load()
        users = self._users(data)
        memories = self._scope_memories(users, scope)
        original_len = len(memories)
        memories[:] = [item for item in memories if str(item.get("id", "")) != str(memory_id)]
        if len(memories) == original_len:
            return False

        self._save(data)
        return True

    def clear_memories(self, scope: str) -> int:
        data = self._load()
        users = self._users(data)
        memories = self._scope_memories(users, scope)
        count = len(memories)
        if count == 0:
            return 0

        users[scope] = []
        self._save(data)
        return count

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "users": {}}

        with self.path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)

        if not isinstance(loaded, dict):
            return {"version": 1, "users": {}}

        if not isinstance(loaded.get("users"), dict):
            loaded["users"] = {}
        loaded["version"] = 1
        return loaded

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def _users(self, data: dict[str, Any]) -> dict[str, Any]:
        users = data.get("users")
        if not isinstance(users, dict):
            users = {}
            data["users"] = users
        return users

    def _scope_memories(self, users: dict[str, Any], scope: str) -> list[dict[str, str]]:
        memories = users.get(scope)
        if not isinstance(memories, list):
            memories = []
            users[scope] = memories
        return memories

    def _trim(self, memories: list[dict[str, str]]) -> None:
        if len(memories) > self.max_items:
            del memories[: len(memories) - self.max_items]

    def _next_id(self, memories: list[dict[str, str]]) -> str:
        numeric_ids = [
            int(str(item.get("id")))
            for item in memories
            if str(item.get("id", "")).isdigit()
        ]
        return str(max(numeric_ids, default=0) + 1)

    def _public_item(self, item: dict[str, str]) -> dict[str, str]:
        return {
            "id": str(item.get("id", "")),
            "content": str(item.get("content", "")),
            "created_at": str(item.get("created_at", "")),
            "updated_at": str(item.get("updated_at", "")),
        }

    def _normalize_content(self, content: str) -> str:
        content = re.sub(r"\s+", " ", content.strip())
        return content[:160].strip()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class UnavailableMemoryStore:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def list_memories(self, scope: str) -> list[dict[str, str]]:
        raise MemoryStoreError(self.reason)

    def add_memory(self, scope: str, content: str, **_: Any) -> dict[str, str] | None:
        raise MemoryStoreError(self.reason)

    def delete_memory(self, scope: str, memory_id: str) -> bool:
        raise MemoryStoreError(self.reason)

    def clear_memories(self, scope: str) -> int:
        raise MemoryStoreError(self.reason)


class MySQLMemoryStore:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        connect_timeout_seconds: int,
        max_items: int = 20,
        import_path: str | None = None,
    ) -> None:
        try:
            self.settings = MySQLConnectionSettings(
                host=host.strip(),
                port=int(port),
                database=database.strip(),
                user=user.strip(),
                password=password,
                connect_timeout_seconds=max(1, int(connect_timeout_seconds)),
            )
        except (TypeError, ValueError) as exc:
            raise MemoryStoreError(str(exc)) from exc
        self.host = self.settings.host
        self.port = self.settings.port
        self.database = self.settings.database
        self.user = self.settings.user
        self.password = self.settings.password
        self.connect_timeout_seconds = self.settings.connect_timeout_seconds
        self.max_items = max(max_items, 1)
        self.import_path = Path(import_path) if import_path else None
        self._validate_config()
        self._ensure_schema()
        self._import_json_memories()

    def list_memories(self, scope: str) -> list[dict[str, str]]:
        try:
            with self._connect() as connection:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        SELECT id, content, created_at, updated_at
                        FROM ai_chat_memories
                        WHERE scope = %s AND is_archived = 0
                        ORDER BY updated_at ASC, id ASC
                        """,
                        (scope,),
                    )
                    rows = cursor.fetchall()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

        return [self._public_item(row) for row in rows]

    def add_memory(
        self,
        scope: str,
        content: str,
        *,
        source: str = "manual",
        category: str = "general",
        confidence: float = 1.0,
    ) -> dict[str, str] | None:
        normalized_content = self._normalize_content(content)
        if not normalized_content:
            return None

        now = self._now()
        content_hash = self._content_hash(normalized_content)
        normalized_source = self._normalize_metadata(source, default="manual", max_length=32)
        normalized_category = self._normalize_metadata(category, default="general", max_length=32)
        normalized_confidence = self._normalize_confidence(confidence)
        try:
            with self._connect() as connection:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO ai_chat_memories
                            (
                                scope,
                                content,
                                content_hash,
                                source,
                                category,
                                confidence,
                                created_at,
                                updated_at,
                                last_used_at,
                                is_archived
                            )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                        ON DUPLICATE KEY UPDATE
                            id = LAST_INSERT_ID(id),
                            content = VALUES(content),
                            source = VALUES(source),
                            category = VALUES(category),
                            confidence = VALUES(confidence),
                            updated_at = VALUES(updated_at),
                            last_used_at = VALUES(last_used_at),
                            is_archived = 0
                        """,
                        (
                            scope,
                            normalized_content,
                            content_hash,
                            normalized_source,
                            normalized_category,
                            normalized_confidence,
                            now,
                            now,
                            now,
                        ),
                    )
                    memory_id = cursor.lastrowid

                    self._trim_scope(cursor, scope)
                    connection.commit()
                    cursor.execute(
                        """
                        SELECT id, content, created_at, updated_at
                        FROM ai_chat_memories
                        WHERE id = %s
                        """,
                        (memory_id,),
                    )
                    row = cursor.fetchone()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

        return self._public_item(row) if row else None

    def delete_memory(self, scope: str, memory_id: str) -> bool:
        if not str(memory_id).isdigit():
            return False

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM ai_chat_memories WHERE scope = %s AND id = %s AND is_archived = 0",
                        (scope, int(memory_id)),
                    )
                    deleted = cursor.rowcount > 0
                connection.commit()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

        return deleted

    def clear_memories(self, scope: str) -> int:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM ai_chat_memories WHERE scope = %s AND is_archived = 0",
                        (scope,),
                    )
                    deleted = cursor.rowcount
                connection.commit()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

        return max(int(deleted), 0)

    def _validate_config(self) -> None:
        missing_keys = [
            key
            for key, value in {
                "MYSQL_HOST": self.settings.host,
                "MYSQL_DATABASE": self.settings.database,
                "MYSQL_USER": self.settings.user,
                "MYSQL_PASSWORD": self.settings.password,
            }.items()
            if not str(value).strip()
        ]
        if missing_keys:
            raise MemoryStoreError(f"MySQL 配置不完整：{', '.join(missing_keys)}")

    def _connect(self):
        return connect_mysql(self.settings)

    def _ensure_schema(self) -> None:
        try:
            run_mysql_migrations(
                self.settings,
                namespace="ai_chat",
                migrations=AI_CHAT_MEMORY_MIGRATIONS,
            )
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

    def _import_json_memories(self) -> None:
        if self.import_path is None or not self.import_path.exists():
            return

        try:
            with self.import_path.open("r", encoding="utf-8") as file:
                loaded = json.load(file)
        except (OSError, json.JSONDecodeError):
            return

        users = loaded.get("users") if isinstance(loaded, dict) else None
        if not isinstance(users, dict):
            return

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    for scope, memories in users.items():
                        if not isinstance(memories, list):
                            continue
                        for item in memories:
                            if not isinstance(item, dict):
                                continue
                            self._import_memory_item(cursor, str(scope), item)
                        self._trim_scope(cursor, str(scope))
                connection.commit()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

    def _import_memory_item(self, cursor, scope: str, item: dict[str, Any]) -> None:
        normalized_content = self._normalize_content(str(item.get("content", "")))
        if not normalized_content:
            return

        content_hash = self._content_hash(normalized_content)
        cursor.execute(
            """
            SELECT id
            FROM ai_chat_memories
            WHERE scope = %s AND content_hash = %s
            LIMIT 1
            """,
            (scope, content_hash),
        )
        if cursor.fetchone():
            return

        now = self._now()
        created_at = self._parse_time(item.get("created_at")) or now
        updated_at = self._parse_time(item.get("updated_at")) or created_at
        last_used_at = self._parse_time(item.get("last_used_at"))
        source = self._normalize_metadata(str(item.get("source", "import")), default="import", max_length=32)
        category = self._normalize_metadata(
            str(item.get("category", "general")),
            default="general",
            max_length=32,
        )
        confidence = self._normalize_confidence(item.get("confidence", 1.0))
        cursor.execute(
            """
            INSERT INTO ai_chat_memories
                (
                    scope,
                    content,
                    content_hash,
                    source,
                    category,
                    confidence,
                    created_at,
                    updated_at,
                    last_used_at,
                    is_archived
                )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
            """,
            (
                scope,
                normalized_content,
                content_hash,
                source,
                category,
                confidence,
                created_at,
                updated_at,
                last_used_at,
            ),
        )

    def _trim_scope(self, cursor, scope: str) -> None:
        cursor.execute(
            "SELECT COUNT(*) FROM ai_chat_memories WHERE scope = %s AND is_archived = 0",
            (scope,),
        )
        row = cursor.fetchone()
        if isinstance(row, dict):
            count = int(next(iter(row.values()), 0))
        else:
            count = int(row[0] if row else 0)
        overflow = count - self.max_items
        if overflow <= 0:
            return

        cursor.execute(
            """
            DELETE FROM ai_chat_memories
            WHERE id IN (
              SELECT id FROM (
                SELECT id
                FROM ai_chat_memories
                WHERE scope = %s AND is_archived = 0
                ORDER BY updated_at ASC, id ASC
                LIMIT %s
              ) AS old_memories
            )
            """,
            (scope, overflow),
        )

    def _normalize_content(self, content: str) -> str:
        content = re.sub(r"\s+", " ", content.strip())
        return content[:160].strip()

    def _normalize_metadata(self, value: str, *, default: str, max_length: int) -> str:
        normalized = re.sub(r"\s+", "_", value.strip().lower())
        normalized = re.sub(r"[^a-z0-9_-]+", "", normalized)
        return (normalized or default)[:max_length]

    def _normalize_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 1.0
        return min(max(confidence, 0.0), 1.0)

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _public_item(self, item: dict[str, Any]) -> dict[str, str]:
        return {
            "id": str(item.get("id", "")),
            "content": str(item.get("content", "")),
            "created_at": self._format_time(item.get("created_at")),
            "updated_at": self._format_time(item.get("updated_at")),
        }

    def _parse_time(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return None

    def _format_time(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        return str(value or "")

    def _now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
