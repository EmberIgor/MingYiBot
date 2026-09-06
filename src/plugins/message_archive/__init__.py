from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nonebot import get_driver, get_plugin_config, logger, on_message, on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from src.common.settings import SettingsStoreError, get_runtime_settings_store
from src.common.background_tasks import create_background_task, register_shutdown_callback

from .config import Config
from .store import (
    ArchivedGroupMessage,
    MessageArchiveError,
    MessageArchiveStore,
    content_hash,
)


__plugin_meta__ = PluginMetadata(
    name="message_archive",
    description="按群归档消息记录，保留后续群画像等能力的数据基础。",
    usage=".群记录 状态\n.群记录 开启\n.群记录 关闭\n.群记录 保留 90",
    config=Config,
)


try:
    LOCAL_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    LOCAL_TZ = timezone(timedelta(hours=8))
MAX_TEXT_LENGTH = 4000
MAX_JSON_LENGTH = 60000

config = get_plugin_config(Config)
driver = get_driver()
runtime_settings = get_runtime_settings_store()
archive_store = MessageArchiveStore(config)
archive_listener = on_message(priority=1, block=False)
archive_control = on_regex(r"^[.。](?:群记录|消息记录)(?:\s+|$).*$", priority=12, block=True)

_last_error_logged_at = 0.0
_archive_queue: asyncio.Queue[ArchivedGroupMessage] = asyncio.Queue(maxsize=config.message_archive_queue_size)
_archive_workers: list[asyncio.Task] = []
_group_retention_days: dict[str, int] = {}
_archive_accepting = True
_last_queue_warning_at = 0.0


@archive_listener.handle()
async def handle_archive_listener(event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    if not await _archive_enabled(event.group_id):
        return

    record = _build_archive_message(event)
    retention_days = await _retention_days(event.group_id)
    _enqueue_archive(record, retention_days)


@archive_control.handle()
async def handle_archive_control(event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        await archive_control.finish(MessageSegment.text("请在群聊中使用群消息记录命令。"))

    command = _parse_prefixed_command(event.get_plaintext(), ("群记录", "消息记录"))
    if not command or command in {"状态", "查看", "status"}:
        await archive_control.finish(MessageSegment.text(await _format_archive_status(event.group_id)))

    if command in {"开启", "开", "enable", "on"}:
        if not _is_superuser(event):
            await archive_control.finish(MessageSegment.text("只有管理员可以修改群消息记录设置。"))
        try:
            await archive_store.ensure_schema_async()
            await runtime_settings.set_value_async(
                "group",
                event.group_id,
                "message_archive",
                "enabled",
                True,
                updated_by=event.user_id,
            )
        except (MessageArchiveError, SettingsStoreError) as exc:
            await archive_control.finish(MessageSegment.text(f"群消息记录开启失败：{exc}"))
        await archive_control.finish(MessageSegment.text("已开启本群消息记录。"))

    if command in {"关闭", "关", "disable", "off"}:
        if not _is_superuser(event):
            await archive_control.finish(MessageSegment.text("只有管理员可以修改群消息记录设置。"))
        try:
            await runtime_settings.set_value_async(
                "group",
                event.group_id,
                "message_archive",
                "enabled",
                False,
                updated_by=event.user_id,
            )
        except SettingsStoreError as exc:
            await archive_control.finish(MessageSegment.text(f"群消息记录关闭失败：{exc}"))
        await archive_control.finish(MessageSegment.text("已关闭本群消息记录。"))

    retention_days = _parse_retention_days(command)
    if retention_days is not None:
        if not _is_superuser(event):
            await archive_control.finish(MessageSegment.text("只有管理员可以修改群消息记录设置。"))
        try:
            await runtime_settings.set_value_async(
                "group",
                event.group_id,
                "message_archive",
                "retention_days",
                retention_days,
                updated_by=event.user_id,
            )
        except SettingsStoreError as exc:
            await archive_control.finish(MessageSegment.text(f"保留天数设置失败：{exc}"))
        await archive_control.finish(MessageSegment.text(f"已设置本群消息记录保留 {retention_days} 天。"))

    await archive_control.finish(
        MessageSegment.text("用法：.群记录 状态 / .群记录 开启 / .群记录 关闭 / .群记录 保留 90")
    )


def _enqueue_archive(record: ArchivedGroupMessage, retention_days: int) -> bool:
    global _last_queue_warning_at
    if not _archive_accepting:
        return False
    _group_retention_days[record.group_id] = retention_days
    try:
        _archive_queue.put_nowait(record)
        return True
    except asyncio.QueueFull:
        now = time.monotonic()
        if now - _last_queue_warning_at >= 60:
            _last_queue_warning_at = now
            logger.warning("Message archive queue is full; new records are being dropped")
        return False


async def _archive_worker(worker_number: int) -> None:
    while True:
        first = await _archive_queue.get()
        batch = [first]
        deadline = asyncio.get_running_loop().time() + config.message_archive_flush_interval_seconds
        try:
            while len(batch) < config.message_archive_batch_size:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(_archive_queue.get(), timeout=remaining))
                except TimeoutError:
                    break
            try:
                await archive_store.record_messages_async(batch)
            except MessageArchiveError as exc:
                _log_archive_error(exc)
        finally:
            for _ in batch:
                _archive_queue.task_done()


async def _archive_prune_scheduler() -> None:
    while True:
        await _prune_known_groups()
        await asyncio.sleep(24 * 60 * 60)


async def _prune_known_groups() -> None:
    try:
        group_ids = set(await archive_store.list_archived_group_ids_async())
    except MessageArchiveError as exc:
        _log_archive_error(exc)
        return
    group_ids.update(_group_retention_days)
    for group_id in group_ids:
        retention_days = _group_retention_days.get(group_id)
        if retention_days is None:
            retention_days = await _retention_days(int(group_id))
        before = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
        try:
            await archive_store.prune_group_before_async(group_id, before.replace(tzinfo=None))
        except MessageArchiveError as exc:
            _log_archive_error(exc)


@driver.on_startup
async def start_archive_workers() -> None:
    global _archive_accepting
    _archive_accepting = True
    if _archive_workers:
        return
    for worker_number in range(config.message_archive_workers):
        task = create_background_task(
            _archive_worker(worker_number),
            name=f"message-archive-worker:{worker_number}",
            key=f"message-archive-worker:{worker_number}",
        )
        if task is not None:
            _archive_workers.append(task)
    create_background_task(
        _archive_prune_scheduler(),
        name="message-archive-pruner",
        key="message-archive-pruner",
    )


async def stop_archive_workers() -> None:
    global _archive_accepting
    _archive_accepting = False
    try:
        await asyncio.wait_for(_archive_queue.join(), timeout=10.0)
    except TimeoutError:
        logger.warning("Message archive queue did not drain before shutdown")
    for task in _archive_workers:
        if not task.done():
            task.cancel()
    if _archive_workers:
        await asyncio.gather(*_archive_workers, return_exceptions=True)
    _archive_workers.clear()


register_shutdown_callback(stop_archive_workers)


async def _format_archive_status(group_id: int) -> str:
    enabled = await _archive_enabled(group_id)
    retention_days = await _retention_days(group_id)
    status = "开启" if enabled else "关闭"
    return f"本群消息记录：{status}\n保留天数：{retention_days} 天"


async def _archive_enabled(group_id: int) -> bool:
    return await runtime_settings.get_bool_async(
        "message_archive",
        "enabled",
        config.message_archive_enabled,
        group_id=group_id,
    )


async def _retention_days(group_id: int) -> int:
    retention_days = await runtime_settings.get_int_async(
        "message_archive",
        "retention_days",
        config.message_archive_retention_days,
        group_id=group_id,
    )
    return max(1, min(retention_days, 3650))


def _build_archive_message(event: GroupMessageEvent) -> ArchivedGroupMessage:
    message = event.get_message()
    message_string = str(message)
    message_json, segment_types = _serialize_message_segments(message)
    sender = event.sender
    return ArchivedGroupMessage(
        group_id=str(event.group_id),
        user_id=str(event.user_id),
        message_id=str(event.message_id),
        bot_id=str(event.self_id),
        sender_nickname=_limit_text(str(sender.nickname or ""), 128),
        sender_card=_limit_text(str(sender.card or ""), 128),
        message_type=str(event.message_type or "group")[:32],
        sub_type=str(event.sub_type or "")[:32],
        message_text=_limit_text(_normalize_text(event.get_plaintext()), MAX_TEXT_LENGTH),
        message_json=_limit_text(message_json, MAX_JSON_LENGTH),
        segment_types=segment_types,
        content_hash=content_hash(message_string),
        sent_at=datetime.fromtimestamp(event.time, tz=timezone.utc).replace(tzinfo=None),
    )


def _serialize_message_segments(message) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    payload = []
    segment_types = []
    for segment in message:
        segment_types.append(segment.type)
        payload.append(
            {
                "type": segment.type,
                "data": dict(segment.data),
            }
        )
    return json.dumps(payload, ensure_ascii=False, default=str), ",".join(segment_types)[:255]


def _parse_prefixed_command(message: str, prefixes: tuple[str, ...]) -> str:
    prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
    return re.sub(rf"^[.。](?:{prefix_pattern})(?:\s+|$)", "", message.strip(), count=1).strip()


def _parse_retention_days(command: str) -> int | None:
    match = re.fullmatch(r"(?:保留|retention)\s*(\d+)\s*(?:天|日|d|day|days)?", command, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _limit_text(text: str, max_length: int) -> str:
    return text[:max_length]


def _is_superuser(event: MessageEvent) -> bool:
    user_id = str(event.user_id).strip()
    return user_id in {str(item).strip() for item in driver.config.superusers}


def _log_archive_error(exc: MessageArchiveError) -> None:
    global _last_error_logged_at
    now = time.monotonic()
    if now - _last_error_logged_at < 60:
        return
    _last_error_logged_at = now
    logger.warning("Message archive skipped: {}", exc)
