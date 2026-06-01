from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from src.common.db import DatabaseError, MySQLMigration, connect_mysql, run_mysql_migrations

from .config import Config


class MessageArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchivedGroupMessage:
    group_id: str
    user_id: str
    message_id: str
    bot_id: str
    sender_nickname: str
    sender_card: str
    message_type: str
    sub_type: str
    message_text: str
    message_json: str
    segment_types: str
    content_hash: str
    sent_at: datetime


@dataclass(frozen=True)
class GroupMessageStats:
    message_count: int
    active_user_count: int
    first_sent_at: datetime | None
    last_sent_at: datetime | None


@dataclass(frozen=True)
class UserMessageCount:
    user_id: str
    display_name: str
    message_count: int


@dataclass(frozen=True)
class KeywordCount:
    keyword: str
    count: int


MESSAGE_ARCHIVE_MIGRATIONS = (
    MySQLMigration(
        version=1,
        name="create_group_message_records",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS group_message_records (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              group_id VARCHAR(64) NOT NULL,
              user_id VARCHAR(64) NOT NULL,
              message_id VARCHAR(128) NOT NULL,
              bot_id VARCHAR(64) NOT NULL DEFAULT '',
              sender_nickname VARCHAR(128) NOT NULL DEFAULT '',
              sender_card VARCHAR(128) NOT NULL DEFAULT '',
              message_type VARCHAR(32) NOT NULL DEFAULT 'group',
              sub_type VARCHAR(32) NOT NULL DEFAULT '',
              message_text TEXT NOT NULL,
              message_json MEDIUMTEXT NOT NULL,
              segment_types VARCHAR(255) NOT NULL DEFAULT '',
              content_hash CHAR(64) NOT NULL,
              sent_at DATETIME NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY uniq_group_message (group_id, message_id),
              KEY idx_group_sent_at (group_id, sent_at),
              KEY idx_group_user_sent_at (group_id, user_id, sent_at),
              KEY idx_group_content_hash (group_id, content_hash)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """,
        ),
    ),
)

TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]{1,}|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]{2,}")
URL_PATTERN = re.compile(r"https?://\S+")
COMMAND_PREFIXES = (".", "。", "/", "!")
EN_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "http",
    "https",
    "that",
    "the",
    "this",
    "with",
    "www",
}
ZH_STOPWORDS = {
    "一个",
    "一下",
    "不是",
    "今天",
    "他们",
    "但是",
    "你们",
    "可以",
    "因为",
    "如果",
    "就是",
    "已经",
    "我们",
    "所以",
    "时候",
    "现在",
    "真的",
    "自己",
    "这个",
    "这么",
    "这样",
    "那个",
    "那么",
    "还是",
    "还有",
    "没有",
    "然后",
    "什么",
    "图片",
    "表情",
}


class MessageArchiveStore:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._schema_ready = False

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        try:
            run_mysql_migrations(
                self.config,
                namespace="message_archive",
                migrations=MESSAGE_ARCHIVE_MIGRATIONS,
            )
        except Exception as exc:
            raise self._archive_error(exc) from exc
        self._schema_ready = True

    async def ensure_schema_async(self) -> None:
        await asyncio.to_thread(self.ensure_schema)

    def record_message(self, message: ArchivedGroupMessage) -> None:
        try:
            self.ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO group_message_records
                            (
                                group_id,
                                user_id,
                                message_id,
                                bot_id,
                                sender_nickname,
                                sender_card,
                                message_type,
                                sub_type,
                                message_text,
                                message_json,
                                segment_types,
                                content_hash,
                                sent_at
                            )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            sender_nickname = VALUES(sender_nickname),
                            sender_card = VALUES(sender_card),
                            message_text = VALUES(message_text),
                            message_json = VALUES(message_json),
                            segment_types = VALUES(segment_types),
                            content_hash = VALUES(content_hash),
                            sent_at = VALUES(sent_at)
                        """,
                        (
                            message.group_id,
                            message.user_id,
                            message.message_id,
                            message.bot_id,
                            message.sender_nickname,
                            message.sender_card,
                            message.message_type,
                            message.sub_type,
                            message.message_text,
                            message.message_json,
                            message.segment_types,
                            message.content_hash,
                            message.sent_at,
                        ),
                    )
                connection.commit()
        except Exception as exc:
            raise self._archive_error(exc) from exc

    async def record_message_async(self, message: ArchivedGroupMessage) -> None:
        await asyncio.to_thread(self.record_message, message)

    def summarize_group(self, group_id: int | str, since: datetime) -> GroupMessageStats:
        try:
            self.ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        SELECT
                            COUNT(*) AS message_count,
                            COUNT(DISTINCT user_id) AS active_user_count,
                            MIN(sent_at) AS first_sent_at,
                            MAX(sent_at) AS last_sent_at
                        FROM group_message_records
                        WHERE group_id = %s AND sent_at >= %s
                        """,
                        (str(group_id), since),
                    )
                    row = cursor.fetchone() or {}
        except Exception as exc:
            raise self._archive_error(exc) from exc

        return GroupMessageStats(
            message_count=int(row.get("message_count") or 0),
            active_user_count=int(row.get("active_user_count") or 0),
            first_sent_at=_datetime_or_none(row.get("first_sent_at")),
            last_sent_at=_datetime_or_none(row.get("last_sent_at")),
        )

    async def summarize_group_async(self, group_id: int | str, since: datetime) -> GroupMessageStats:
        return await asyncio.to_thread(self.summarize_group, group_id, since)

    def top_users(self, group_id: int | str, since: datetime, *, limit: int = 5) -> list[UserMessageCount]:
        try:
            self.ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        SELECT
                            user_id,
                            MAX(sender_nickname) AS sender_nickname,
                            MAX(sender_card) AS sender_card,
                            COUNT(*) AS message_count
                        FROM group_message_records
                        WHERE group_id = %s AND sent_at >= %s
                        GROUP BY user_id
                        ORDER BY message_count DESC, user_id ASC
                        LIMIT %s
                        """,
                        (str(group_id), since, max(1, int(limit))),
                    )
                    rows = cursor.fetchall()
        except Exception as exc:
            raise self._archive_error(exc) from exc

        return [
            UserMessageCount(
                user_id=str(row.get("user_id") or ""),
                display_name=_display_name(row),
                message_count=int(row.get("message_count") or 0),
            )
            for row in rows
        ]

    async def top_users_async(
        self,
        group_id: int | str,
        since: datetime,
        *,
        limit: int = 5,
    ) -> list[UserMessageCount]:
        return await asyncio.to_thread(self.top_users, group_id, since, limit=limit)

    def recent_texts(self, group_id: int | str, since: datetime, *, limit: int) -> list[str]:
        try:
            self.ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT message_text
                        FROM group_message_records
                        WHERE group_id = %s
                          AND sent_at >= %s
                          AND message_text <> ''
                        ORDER BY sent_at DESC, id DESC
                        LIMIT %s
                        """,
                        (str(group_id), since, max(1, int(limit))),
                    )
                    rows = cursor.fetchall()
        except Exception as exc:
            raise self._archive_error(exc) from exc

        return [str(row[0]).strip() for row in rows if row and str(row[0]).strip()]

    async def recent_texts_async(self, group_id: int | str, since: datetime, *, limit: int) -> list[str]:
        return await asyncio.to_thread(self.recent_texts, group_id, since, limit=limit)

    def prune_group_before(self, group_id: int | str, before: datetime) -> int:
        try:
            self.ensure_schema()
            with connect_mysql(self.config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM group_message_records
                        WHERE group_id = %s AND sent_at < %s
                        """,
                        (str(group_id), before),
                    )
                    deleted = int(cursor.rowcount or 0)
                connection.commit()
        except Exception as exc:
            raise self._archive_error(exc) from exc
        return deleted

    async def prune_group_before_async(self, group_id: int | str, before: datetime) -> int:
        return await asyncio.to_thread(self.prune_group_before, group_id, before)

    def _archive_error(self, exc: Exception) -> MessageArchiveError:
        if isinstance(exc, MessageArchiveError):
            return exc
        if isinstance(exc, DatabaseError):
            return MessageArchiveError(str(exc))
        return MessageArchiveError(str(exc))


def extract_keywords(texts: Iterable[str], *, limit: int = 12) -> list[KeywordCount]:
    counts: Counter[str] = Counter()
    for text in texts:
        normalized_text = URL_PATTERN.sub(" ", text).strip()
        if not normalized_text or normalized_text.startswith(COMMAND_PREFIXES):
            continue
        for token in TOKEN_PATTERN.findall(normalized_text.lower()):
            for keyword in _expand_keyword_token(token):
                counts[keyword] += 1

    return [
        KeywordCount(keyword=keyword, count=count)
        for keyword, count in counts.most_common(max(1, int(limit)))
    ]


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expand_keyword_token(token: str) -> Iterable[str]:
    if re.fullmatch(r"[\u4e00-\u9fff]+", token):
        if token in ZH_STOPWORDS:
            return []
        if len(token) <= 6:
            return [token]
        return [
            token[index : index + 2]
            for index in range(len(token) - 1)
            if token[index : index + 2] not in ZH_STOPWORDS
        ]

    if token in EN_STOPWORDS or len(token) < 2:
        return []
    return [token]


def _display_name(row: dict[str, Any]) -> str:
    card = str(row.get("sender_card") or "").strip()
    nickname = str(row.get("sender_nickname") or "").strip()
    user_id = str(row.get("user_id") or "").strip()
    return card or nickname or user_id


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return None
