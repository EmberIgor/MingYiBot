from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

    def add_memory(self, scope: str, content: str) -> dict[str, str] | None:
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
