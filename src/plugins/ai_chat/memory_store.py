from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
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
            self._public_item(item)
            for item in memories
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ]

    def add_memory(self, scope: str, content: str, **_: Any) -> dict[str, str] | None:
        source = self._normalize_metadata(str(_.get("source", "manual")), default="manual", max_length=32)
        category = self._normalize_metadata(str(_.get("category", "general")), default="general", max_length=32)
        confidence = self._normalize_confidence(_.get("confidence", 1.0))
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
                item["source"] = self._merged_source(str(item.get("source", "")), source)
                item["category"] = category
                item["confidence"] = confidence
                item["updated_at"] = now
                memories.remove(item)
                memories.append(item)
                self._trim(memories)
                self._save(data)
                return self._public_item(item)

        similar_item = self._find_similar_item(memories, normalized_content)
        if similar_item is not None:
            incoming = {
                "content": normalized_content,
                "source": source,
                "category": category,
                "confidence": confidence,
                "created_at": now,
                "updated_at": now,
            }
            if self._should_replace_memory(similar_item, incoming):
                similar_item["content"] = normalized_content
                similar_item["source"] = self._merged_source(str(similar_item.get("source", "")), source)
                similar_item["category"] = category
                similar_item["confidence"] = confidence
                similar_item["updated_at"] = now
                memories.remove(similar_item)
                memories.append(similar_item)
            self._trim(memories)
            self._save(data)
            return self._public_item(similar_item)

        item = {
            "id": self._next_id(memories),
            "content": normalized_content,
            "source": source,
            "category": category,
            "confidence": confidence,
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

    def compact_memories(self, scope: str) -> dict[str, int]:
        data = self._load()
        users = self._users(data)
        memories = self._scope_memories(users, scope)
        original_count = len(memories)
        compacted: list[dict[str, Any]] = []

        for item in memories:
            if not isinstance(item, dict):
                continue
            content = self._normalize_content(str(item.get("content", "")))
            if not content:
                continue
            item["content"] = content
            similar_item = self._find_similar_item(compacted, content)
            if similar_item is None:
                compacted.append(item)
                continue
            if self._should_replace_memory(similar_item, item):
                compacted.remove(similar_item)
                compacted.append(item)

        users[scope] = compacted
        self._trim(compacted)
        removed_count = original_count - len(compacted)
        if removed_count > 0:
            self._save(data)
        return {"kept": len(compacted), "removed": max(removed_count, 0)}

    def replace_memories(
        self,
        scope: str,
        contents: list[str],
        *,
        source: str = "manual",
        category: str = "organized",
        confidence: float = 0.9,
    ) -> dict[str, int]:
        data = self._load()
        users = self._users(data)
        old_memories = self._scope_memories(users, scope)
        old_count = len(old_memories)
        now = self._now()
        normalized_source = self._normalize_metadata(source, default="manual", max_length=32)
        normalized_category = self._normalize_metadata(category, default="organized", max_length=32)
        normalized_confidence = self._normalize_confidence(confidence)
        new_memories: list[dict[str, Any]] = []

        for content in contents:
            normalized_content = self._normalize_content(content)
            if not normalized_content:
                continue
            similar_item = self._find_similar_item(new_memories, normalized_content)
            incoming = {
                "id": str(len(new_memories) + 1),
                "content": normalized_content,
                "source": normalized_source,
                "category": normalized_category,
                "confidence": normalized_confidence,
                "created_at": now,
                "updated_at": now,
            }
            if similar_item is None:
                new_memories.append(incoming)
            elif self._should_replace_memory(similar_item, incoming):
                new_memories.remove(similar_item)
                incoming["id"] = str(len(new_memories) + 1)
                new_memories.append(incoming)

        self._trim(new_memories)
        users[scope] = new_memories
        self._save(data)
        return {"kept": len(new_memories), "removed": max(old_count - len(new_memories), 0)}

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
        while len(memories) > self.max_items:
            delete_index = min(
                range(len(memories)),
                key=lambda index: self._trim_key(memories[index]),
            )
            del memories[delete_index]

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
            "source": str(item.get("source", "manual")),
            "category": str(item.get("category", "general")),
            "confidence": str(item.get("confidence", "1.0")),
        }

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

    def _find_similar_item(
        self,
        memories: list[dict[str, Any]],
        normalized_content: str,
    ) -> dict[str, Any] | None:
        for item in memories:
            if self._is_similar_memory(str(item.get("content", "")), normalized_content):
                return item
        return None

    def _is_similar_memory(self, first: str, second: str) -> bool:
        first_key = self._memory_key(first)
        second_key = self._memory_key(second)
        if not first_key or not second_key:
            return False
        if first_key == second_key:
            return True

        shorter, longer = sorted((first_key, second_key), key=len)
        if len(shorter) >= 8 and shorter in longer and len(shorter) / len(longer) >= 0.45:
            return True

        if len(shorter) < 10:
            return False

        sequence_ratio = SequenceMatcher(None, first_key, second_key).ratio()
        if sequence_ratio >= 0.72:
            return True

        return len(shorter) >= 20 and self._ngram_dice(first_key, second_key, 2) >= 0.45

    def _memory_key(self, content: str) -> str:
        content = re.sub(r"\s+", "", content.strip().lower())
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", content)

    def _ngram_dice(self, first: str, second: str, size: int) -> float:
        if len(first) < size or len(second) < size:
            return 0.0
        first_grams = {first[index : index + size] for index in range(len(first) - size + 1)}
        second_grams = {second[index : index + size] for index in range(len(second) - size + 1)}
        if not first_grams or not second_grams:
            return 0.0
        return 2 * len(first_grams & second_grams) / (len(first_grams) + len(second_grams))

    def _should_replace_memory(self, existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
        existing_rank = self._source_rank(str(existing.get("source", "")))
        incoming_rank = self._source_rank(str(incoming.get("source", "")))
        if incoming_rank > existing_rank:
            return True
        if incoming_rank < existing_rank:
            return False

        existing_specificity = len(self._memory_key(str(existing.get("content", ""))))
        incoming_specificity = len(self._memory_key(str(incoming.get("content", ""))))
        if incoming_specificity > existing_specificity:
            return True
        if incoming_specificity < existing_specificity * 0.7:
            return False
        return str(incoming.get("updated_at", "")) >= str(existing.get("updated_at", ""))

    def _source_rank(self, source: str) -> int:
        normalized_source = self._normalize_metadata(source, default="import", max_length=32)
        if normalized_source in {"manual", "explicit_chat"}:
            return 3
        if normalized_source == "summary":
            return 2
        return 1

    def _merged_source(self, existing_source: str, incoming_source: str) -> str:
        existing_rank = self._source_rank(existing_source)
        incoming_rank = self._source_rank(incoming_source)
        return incoming_source if incoming_rank >= existing_rank else existing_source

    def _trim_key(self, item: dict[str, Any]) -> tuple[int, str, str]:
        return (
            self._source_rank(str(item.get("source", ""))),
            str(item.get("updated_at") or item.get("created_at") or ""),
            str(item.get("id", "")),
        )

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

    def compact_memories(self, scope: str) -> dict[str, int]:
        raise MemoryStoreError(self.reason)

    def replace_memories(
        self,
        scope: str,
        contents: list[str],
        **_: Any,
    ) -> dict[str, int]:
        raise MemoryStoreError(self.reason)


class MySQLMemoryStore(MemoryStore):
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
                        SELECT id, content, source, category, confidence, created_at, updated_at
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
                    similar_item = self._find_similar_active_item(cursor, scope, normalized_content)
                    if similar_item is not None:
                        if self._should_replace_memory(similar_item, {
                            "content": normalized_content,
                            "source": normalized_source,
                            "category": normalized_category,
                            "confidence": normalized_confidence,
                            "updated_at": now,
                        }):
                            cursor.execute(
                                """
                                UPDATE ai_chat_memories
                                SET content = %s,
                                    content_hash = %s,
                                    source = %s,
                                    category = %s,
                                    confidence = %s,
                                    updated_at = %s,
                                    last_used_at = %s,
                                    is_archived = 0
                                WHERE id = %s
                                """,
                                (
                                    normalized_content,
                                    content_hash,
                                    self._merged_source(str(similar_item.get("source", "")), normalized_source),
                                    normalized_category,
                                    normalized_confidence,
                                    now,
                                    now,
                                    similar_item["id"],
                                ),
                            )
                            memory_id = similar_item["id"]
                        else:
                            memory_id = similar_item["id"]
                        self._trim_scope(cursor, scope)
                        connection.commit()
                        cursor.execute(
                            """
                            SELECT id, content, source, category, confidence, created_at, updated_at
                            FROM ai_chat_memories
                            WHERE id = %s
                            """,
                            (memory_id,),
                        )
                        row = cursor.fetchone()
                        return self._public_item(row) if row else None

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
                        SELECT id, content, source, category, confidence, created_at, updated_at
                        FROM ai_chat_memories
                        WHERE id = %s
                        """,
                        (memory_id,),
                    )
                    row = cursor.fetchone()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

        return self._public_item(row) if row else None

    def compact_memories(self, scope: str) -> dict[str, int]:
        try:
            with self._connect() as connection:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        SELECT id, content, source, category, confidence, created_at, updated_at
                        FROM ai_chat_memories
                        WHERE scope = %s AND is_archived = 0
                        ORDER BY updated_at ASC, id ASC
                        """,
                        (scope,),
                    )
                    rows = cursor.fetchall()
                    kept: list[dict[str, Any]] = []
                    delete_ids: list[int] = []
                    for row in rows:
                        similar_item = self._find_similar_item(kept, str(row.get("content", "")))
                        if similar_item is None:
                            kept.append(row)
                            continue
                        if self._should_replace_memory(similar_item, row):
                            kept.remove(similar_item)
                            delete_ids.append(int(similar_item["id"]))
                            kept.append(row)
                        else:
                            delete_ids.append(int(row["id"]))

                    for memory_id in delete_ids:
                        cursor.execute(
                            "DELETE FROM ai_chat_memories WHERE scope = %s AND id = %s",
                            (scope, memory_id),
                        )
                    self._trim_scope(cursor, scope)
                connection.commit()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

        return {"kept": len(rows) - len(delete_ids), "removed": len(delete_ids)}

    def replace_memories(
        self,
        scope: str,
        contents: list[str],
        *,
        source: str = "manual",
        category: str = "organized",
        confidence: float = 0.9,
    ) -> dict[str, int]:
        now = self._now()
        normalized_source = self._normalize_metadata(source, default="manual", max_length=32)
        normalized_category = self._normalize_metadata(category, default="organized", max_length=32)
        normalized_confidence = self._normalize_confidence(confidence)
        new_items: list[dict[str, Any]] = []
        for content in contents:
            normalized_content = self._normalize_content(content)
            if not normalized_content:
                continue
            incoming = {
                "content": normalized_content,
                "source": normalized_source,
                "category": normalized_category,
                "confidence": normalized_confidence,
                "updated_at": now,
            }
            similar_item = self._find_similar_item(new_items, normalized_content)
            if similar_item is None:
                new_items.append(incoming)
            elif self._should_replace_memory(similar_item, incoming):
                new_items.remove(similar_item)
                new_items.append(incoming)
            if len(new_items) >= self.max_items:
                break
        normalized_contents = [str(item["content"]) for item in new_items]

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM ai_chat_memories WHERE scope = %s AND is_archived = 0",
                        (scope,),
                    )
                    row = cursor.fetchone()
                    if isinstance(row, dict):
                        old_count = int(next(iter(row.values()), 0))
                    else:
                        old_count = int(row[0] if row else 0)

                    cursor.execute(
                        "DELETE FROM ai_chat_memories WHERE scope = %s AND is_archived = 0",
                        (scope,),
                    )
                    for content in normalized_contents:
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
                                content,
                                self._content_hash(content),
                                normalized_source,
                                normalized_category,
                                normalized_confidence,
                                now,
                                now,
                                now,
                            ),
                        )
                connection.commit()
        except Exception as exc:
            raise MemoryStoreError(str(exc)) from exc

        return {"kept": len(normalized_contents), "removed": max(old_count - len(normalized_contents), 0)}

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
                ORDER BY
                  CASE
                    WHEN source IN ('manual', 'explicit_chat') THEN 2
                    WHEN source = 'summary' THEN 1
                    ELSE 0
                  END ASC,
                  updated_at ASC,
                  id ASC
                LIMIT %s
              ) AS old_memories
            )
            """,
            (scope, overflow),
        )

    def _find_similar_active_item(self, cursor, scope: str, normalized_content: str) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT id, content, source, category, confidence, created_at, updated_at
            FROM ai_chat_memories
            WHERE scope = %s AND is_archived = 0
            ORDER BY updated_at ASC, id ASC
            """,
            (scope,),
        )
        return self._find_similar_item(cursor.fetchall(), normalized_content)

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
            "source": str(item.get("source", "manual")),
            "category": str(item.get("category", "general")),
            "confidence": str(item.get("confidence", "1.0")),
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
