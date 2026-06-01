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

from .config import Config
from .store import (
    ArchivedGroupMessage,
    MessageArchiveError,
    MessageArchiveStore,
    content_hash,
    extract_keywords,
)


__plugin_meta__ = PluginMetadata(
    name="message_archive",
    description="按群归档消息记录，并提供基础群统计和热词查询。",
    usage=".群记录 状态\n.群记录 开启\n.群统计 今日\n.群热词 7天\n私聊管理员：.群统计 群号 今日",
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
group_stats = on_regex(r"^[.。]群统计(?:\s+|$).*$", priority=12, block=True)
group_hotwords = on_regex(r"^[.。]群热词(?:\s+|$).*$", priority=12, block=True)
PRIVATE_GROUP_QUERY_PATTERN = re.compile(r"^(?:群(?:号|聊)?[:：]?\s*)?(\d{5,20})(?:\s+(.+))?$")

_last_error_logged_at = 0.0
_last_pruned_dates: dict[str, str] = {}


@archive_listener.handle()
async def handle_archive_listener(event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    if not await _archive_enabled(event.group_id):
        return

    record = _build_archive_message(event)
    retention_days = await _retention_days(event.group_id)
    asyncio.create_task(_record_group_message(record, retention_days))


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


@group_stats.handle()
async def handle_group_stats(event: MessageEvent) -> None:
    command = _parse_prefixed_command(event.get_plaintext(), ("群统计",))
    if isinstance(event, GroupMessageEvent):
        response = await _format_group_stats_response(event.group_id, command, group_label="本群")
    else:
        response = await _format_private_group_stats_response(event, command)
    await group_stats.finish(MessageSegment.text(response))


@group_hotwords.handle()
async def handle_group_hotwords(event: MessageEvent) -> None:
    command = _parse_prefixed_command(event.get_plaintext(), ("群热词",))
    if isinstance(event, GroupMessageEvent):
        response = await _format_group_hotwords_response(event.group_id, command, group_label="本群")
    else:
        response = await _format_private_group_hotwords_response(event, command)
    await group_hotwords.finish(MessageSegment.text(response))


async def _format_private_group_stats_response(event: MessageEvent, command: str) -> str:
    if not _is_superuser(event):
        return "只有管理员可以通过私聊查询指定群统计。"

    query = _parse_private_group_query(command)
    if query is None:
        return "用法：.群统计 群号 时间范围，例如 .群统计 123456 今日"

    group_id, period_command = query
    return await _format_group_stats_response(group_id, period_command, group_label=f"群 {group_id} ")


async def _format_private_group_hotwords_response(event: MessageEvent, command: str) -> str:
    if not _is_superuser(event):
        return "只有管理员可以通过私聊查询指定群热词。"

    query = _parse_private_group_query(command)
    if query is None:
        return "用法：.群热词 群号 时间范围，例如 .群热词 123456 7天"

    group_id, period_command = query
    return await _format_group_hotwords_response(group_id, period_command, group_label=f"群 {group_id} ")


async def _format_group_stats_response(group_id: int, command: str, *, group_label: str) -> str:
    if not await _archive_enabled(group_id):
        return f"{group_label}消息记录未开启，请管理员先发送 .群记录 开启。"

    since, period_label = _parse_period(command, default_days=1)
    try:
        stats = await archive_store.summarize_group_async(group_id, since)
        top_users = await archive_store.top_users_async(group_id, since, limit=5)
    except MessageArchiveError as exc:
        return f"群统计查询失败：{exc}"

    if stats.message_count == 0:
        return f"{group_label}{period_label}还没有消息记录。"

    lines = [
        f"{group_label}{period_label}统计：",
        f"消息：{stats.message_count} 条",
        f"活跃用户：{stats.active_user_count} 人",
    ]
    if stats.first_sent_at and stats.last_sent_at:
        lines.append(f"时间：{_format_datetime(stats.first_sent_at)} 至 {_format_datetime(stats.last_sent_at)}")
    if top_users:
        lines.append("发言榜：")
        lines.extend(
            f"{index}. {_format_user_count(item.display_name, item.user_id)}：{item.message_count} 条"
            for index, item in enumerate(top_users, 1)
        )
    return "\n".join(lines)


async def _format_group_hotwords_response(group_id: int, command: str, *, group_label: str) -> str:
    if not await _archive_enabled(group_id):
        return f"{group_label}消息记录未开启，请管理员先发送 .群记录 开启。"

    since, period_label = _parse_period(command, default_days=7)
    try:
        texts = await archive_store.recent_texts_async(
            group_id,
            since,
            limit=config.message_archive_query_limit,
        )
    except MessageArchiveError as exc:
        return f"群热词查询失败：{exc}"

    keywords = extract_keywords(texts, limit=config.message_archive_hotword_limit)
    if not keywords:
        return f"{group_label}{period_label}还没有可统计的文本热词。"

    lines = [f"{group_label}{period_label}热词："]
    lines.extend(f"{index}. {item.keyword}：{item.count}" for index, item in enumerate(keywords, 1))
    return "\n".join(lines)


async def _record_group_message(record: ArchivedGroupMessage, retention_days: int) -> None:
    try:
        await archive_store.record_message_async(record)
        await _maybe_prune_group(record.group_id, retention_days)
    except MessageArchiveError as exc:
        _log_archive_error(exc)


async def _maybe_prune_group(group_id: str, retention_days: int) -> None:
    today_key = datetime.now(LOCAL_TZ).date().isoformat()
    prune_key = f"{group_id}:{today_key}"
    if _last_pruned_dates.get(group_id) == prune_key:
        return
    before = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    await archive_store.prune_group_before_async(group_id, before.replace(tzinfo=None))
    _last_pruned_dates[group_id] = prune_key


async def _format_archive_status(group_id: int) -> str:
    enabled = await _archive_enabled(group_id)
    retention_days = await _retention_days(group_id)
    status = "开启" if enabled else "关闭"
    return f"本群消息记录：{status}\n保留天数：{retention_days} 天\n统计命令：.群统计 今日 / .群热词 7天"


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


def _parse_private_group_query(command: str) -> tuple[int, str] | None:
    match = PRIVATE_GROUP_QUERY_PATTERN.fullmatch(command.strip())
    if not match:
        return None
    return int(match.group(1)), (match.group(2) or "").strip()


def _parse_retention_days(command: str) -> int | None:
    match = re.fullmatch(r"(?:保留|retention)\s*(\d+)\s*(?:天|日|d|day|days)?", command, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _parse_period(command: str, *, default_days: int) -> tuple[datetime, str]:
    command = command.strip()
    now_utc = datetime.now(timezone.utc)
    if not command and default_days == 1:
        return _today_start_utc_naive(now_utc), "今日"
    if command in {"今日", "今天", "today"}:
        return _today_start_utc_naive(now_utc), "今日"

    days = default_days
    match = re.search(r"(\d+)\s*(?:天|日|d|day|days)", command, flags=re.IGNORECASE)
    if match:
        days = max(1, min(int(match.group(1)), 365))
    since = now_utc - timedelta(days=days)
    return since.replace(tzinfo=None), f"近{days}天"


def _today_start_utc_naive(now_utc: datetime) -> datetime:
    local_now = now_utc.astimezone(LOCAL_TZ)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def _format_datetime(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).strftime("%m-%d %H:%M")


def _format_user_count(display_name: str, user_id: str) -> str:
    display_name = display_name.strip()
    if not display_name or display_name == user_id:
        return user_id
    return f"{display_name}({user_id})"


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
