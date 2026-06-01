from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime

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


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
