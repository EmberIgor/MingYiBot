from __future__ import annotations

import re
from typing import Any

from nonebot import get_driver, get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from src.common.settings import SettingsStoreError, get_runtime_settings_store
from src.plugins.ai_chat.config import Config as AIChatConfig
from src.plugins.ai_chat.role_store import RoleStore
from src.plugins.daily_news.config import Config as DailyNewsConfig
from src.plugins.message_archive.config import Config as MessageArchiveConfig
from src.plugins.repeater.config import Config as RepeaterConfig
from src.plugins.sunset.config import Config as SunsetConfig


__plugin_meta__ = PluginMetadata(
    name="runtime_config",
    description="管理员在群聊中热修改非敏感运行时配置。",
    usage=(
        ".配置 查看\n"
        ".配置 每日新闻 开|关\n"
        ".配置 火烧云城市 上海\n"
        ".配置 AI联网 开|关\n"
        ".配置 默认角色 jarvis\n"
        ".配置 复读阈值 3\n"
        ".配置 群记录 开|关\n"
        ".配置 重置 火烧云城市"
    ),
)


driver = get_driver()
runtime_settings = get_runtime_settings_store()
daily_news_config = get_plugin_config(DailyNewsConfig)
sunset_config = get_plugin_config(SunsetConfig)
ai_chat_config = get_plugin_config(AIChatConfig)
repeater_config = get_plugin_config(RepeaterConfig)
message_archive_config = get_plugin_config(MessageArchiveConfig)
runtime_config = on_regex(r"^[.。]配置(?:\s+|$)(.*)$", priority=8, block=True)

RESET_ALIASES: dict[str, tuple[str, str]] = {
    "每日新闻": ("daily_news", "enabled"),
    "火烧云城市": ("sunset", "default_city"),
    "ai联网": ("ai_chat", "web_search"),
    "AI联网": ("ai_chat", "web_search"),
    "默认角色": ("ai_chat", "default_role"),
    "复读阈值": ("repeater", "threshold"),
    "群记录": ("message_archive", "enabled"),
    "消息记录": ("message_archive", "enabled"),
    "群记录保留": ("message_archive", "retention_days"),
    "群记录保留天数": ("message_archive", "retention_days"),
    "消息记录保留": ("message_archive", "retention_days"),
    "消息记录保留天数": ("message_archive", "retention_days"),
}
GLOBAL_SETTINGS = set(RESET_ALIASES.values())
GROUP_SETTINGS = set(RESET_ALIASES.values())


@runtime_config.handle()
async def handle_runtime_config(event: MessageEvent) -> None:
    if not _is_superuser(event):
        await runtime_config.finish(MessageSegment.text("只有管理员可以修改运行时配置。"))

    command = _parse_config_command(event.get_plaintext())
    if not command or command in {"帮助", "help"}:
        await runtime_config.finish(MessageSegment.text(_help_text(is_group=isinstance(event, GroupMessageEvent))))

    updated_by = event.user_id

    try:
        if isinstance(event, GroupMessageEvent):
            response = await _handle_group_config(command, event.group_id, updated_by)
        else:
            response = await _handle_private_config(command, updated_by)
    except SettingsStoreError as exc:
        logger.warning("Runtime config command failed: {}", exc)
        await runtime_config.finish(MessageSegment.text(f"配置失败：{exc}"))

    await runtime_config.finish(MessageSegment.text(response))


async def _handle_group_config(command: str, group_id: int, updated_by: int) -> str:
    if command in {"查看", "list"}:
        return await _format_group_settings(group_id)

    return await _apply_scope_setting(
        command,
        "group",
        group_id,
        updated_by,
        scope_label="当前群",
        allowed_settings=GROUP_SETTINGS,
    )


async def _handle_private_config(command: str, updated_by: int) -> str:
    if command in {"查看", "list", "全局 查看", "全局 list"}:
        return await _format_global_settings()

    if command.startswith("全局 "):
        command = command.removeprefix("全局 ").strip()

    return await _apply_scope_setting(
        command,
        "global",
        None,
        updated_by,
        scope_label="全局",
        allowed_settings=GLOBAL_SETTINGS,
    )


async def _apply_scope_setting(
    command: str,
    scope_type: ScopeType,
    scope_id: int | None,
    updated_by: int,
    *,
    scope_label: str,
    allowed_settings: set[tuple[str, str]],
) -> str:
    if command in {"每日新闻 开", "每日新闻 开启"}:
        _require_allowed(("daily_news", "enabled"), allowed_settings, scope_label)
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "daily_news",
            "enabled",
            True,
            updated_by=updated_by,
        )
        return f"已开启{scope_label}的每日新闻。"

    if command in {"每日新闻 关", "每日新闻 关闭"}:
        _require_allowed(("daily_news", "enabled"), allowed_settings, scope_label)
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "daily_news",
            "enabled",
            False,
            updated_by=updated_by,
        )
        return f"已关闭{scope_label}的每日新闻。"

    match = re.fullmatch(r"火烧云城市\s+(.+)", command)
    if match:
        _require_allowed(("sunset", "default_city"), allowed_settings, scope_label)
        city = match.group(1).strip()
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "sunset",
            "default_city",
            city,
            updated_by=updated_by,
        )
        return f"已将{scope_label}火烧云默认城市设为：{city}"

    if command in {"AI联网 开", "AI联网 开启", "ai联网 开", "ai联网 开启"}:
        _require_allowed(("ai_chat", "web_search"), allowed_settings, scope_label)
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "ai_chat",
            "web_search",
            True,
            updated_by=updated_by,
        )
        return f"已开启{scope_label} AI 联网。"

    if command in {"AI联网 关", "AI联网 关闭", "ai联网 关", "ai联网 关闭"}:
        _require_allowed(("ai_chat", "web_search"), allowed_settings, scope_label)
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "ai_chat",
            "web_search",
            False,
            updated_by=updated_by,
        )
        return f"已关闭{scope_label} AI 联网。"

    match = re.fullmatch(r"默认角色\s+(\S+)", command)
    if match:
        _require_allowed(("ai_chat", "default_role"), allowed_settings, scope_label)
        role_name = match.group(1).strip()
        role_store = RoleStore(ai_chat_config.aichat_roles_path, ai_chat_config.aichat_default_role)
        if not role_store.has_role(role_name):
            return f"没有找到角色：{role_name}\n可用角色：{'、'.join(role_store.list_roles())}"
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "ai_chat",
            "default_role",
            role_name,
            updated_by=updated_by,
        )
        return f"已将{scope_label}默认 AI 角色设为：{role_name}"

    match = re.fullmatch(r"复读阈值\s+(\d+)", command)
    if match:
        _require_allowed(("repeater", "threshold"), allowed_settings, scope_label)
        threshold = int(match.group(1))
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "repeater",
            "threshold",
            threshold,
            updated_by=updated_by,
        )
        if threshold < 2:
            return f"已关闭{scope_label}复读。"
        return f"已将{scope_label}复读阈值设为：{threshold}"

    if command in {"群记录 开", "群记录 开启", "消息记录 开", "消息记录 开启"}:
        _require_allowed(("message_archive", "enabled"), allowed_settings, scope_label)
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "message_archive",
            "enabled",
            True,
            updated_by=updated_by,
        )
        return f"已开启{scope_label}群消息记录。"

    if command in {"群记录 关", "群记录 关闭", "消息记录 关", "消息记录 关闭"}:
        _require_allowed(("message_archive", "enabled"), allowed_settings, scope_label)
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "message_archive",
            "enabled",
            False,
            updated_by=updated_by,
        )
        return f"已关闭{scope_label}群消息记录。"

    match = re.fullmatch(r"(?:群记录|消息记录)\s*(?:保留|保留天数)\s+(\d+)", command)
    if match:
        _require_allowed(("message_archive", "retention_days"), allowed_settings, scope_label)
        retention_days = int(match.group(1))
        await runtime_settings.set_value_async(
            scope_type,
            scope_id,
            "message_archive",
            "retention_days",
            retention_days,
            updated_by=updated_by,
        )
        return f"已将{scope_label}群消息记录保留天数设为：{retention_days}"

    match = re.fullmatch(r"重置\s+(.+)", command)
    if match:
        target = match.group(1).strip()
        setting = RESET_ALIASES.get(target)
        if setting is None:
            return f"不知道要重置哪项配置：{target}\n可重置：{'、'.join(RESET_ALIASES)}"
        _require_allowed(setting, allowed_settings, scope_label)
        deleted = await runtime_settings.delete_value_async(scope_type, scope_id, setting[0], setting[1])
        return f"已重置{scope_label}配置。" if deleted else f"{scope_label}没有设置过这项配置。"

    return _help_text(is_group=scope_type == "group")


async def _format_group_settings(group_id: int) -> str:
    try:
        stored_values = await runtime_settings.list_scope_values_async("group", group_id)
        daily_news_enabled = await runtime_settings.get_bool_async(
            "daily_news",
            "enabled",
            _daily_news_env_default(group_id),
            group_id=group_id,
        )
        sunset_city = await runtime_settings.get_str_async(
            "sunset",
            "default_city",
            sunset_config.sunset_default_city,
            group_id=group_id,
        )
        ai_web_search = await runtime_settings.get_bool_async(
            "ai_chat",
            "web_search",
            ai_chat_config.aichat_web_search,
            group_id=group_id,
        )
        ai_default_role = await runtime_settings.get_str_async(
            "ai_chat",
            "default_role",
            ai_chat_config.aichat_default_role,
            group_id=group_id,
        )
        repeater_threshold = await runtime_settings.get_int_async(
            "repeater",
            "threshold",
            repeater_config.repeater_threshold,
            group_id=group_id,
        )
        message_archive_enabled = await runtime_settings.get_bool_async(
            "message_archive",
            "enabled",
            message_archive_config.message_archive_enabled,
            group_id=group_id,
        )
        message_archive_retention_days = await runtime_settings.get_int_async(
            "message_archive",
            "retention_days",
            message_archive_config.message_archive_retention_days,
            group_id=group_id,
        )
    except SettingsStoreError as exc:
        raise SettingsStoreError(str(exc)) from exc

    lines = [f"当前群运行时配置（{group_id}）："]
    lines.append(f"每日新闻：{_on_off(daily_news_enabled)}{_source(stored_values, 'daily_news', 'enabled')}")
    lines.append(f"火烧云城市：{sunset_city}{_source(stored_values, 'sunset', 'default_city')}")
    lines.append(f"AI联网：{_on_off(ai_web_search)}{_source(stored_values, 'ai_chat', 'web_search')}")
    lines.append(f"默认角色：{ai_default_role}{_source(stored_values, 'ai_chat', 'default_role')}")
    repeater_text = "关闭" if repeater_threshold < 2 else str(repeater_threshold)
    lines.append(f"复读阈值：{repeater_text}{_source(stored_values, 'repeater', 'threshold')}")
    lines.append(
        f"群消息记录：{_on_off(message_archive_enabled)}"
        f"{_source(stored_values, 'message_archive', 'enabled')}"
    )
    lines.append(
        f"群消息记录保留：{message_archive_retention_days} 天"
        f"{_source(stored_values, 'message_archive', 'retention_days')}"
    )
    return "\n".join(lines)


def _daily_news_env_default(group_id: int) -> bool:
    group_ids = set(daily_news_config.dailynews_group_ids)
    if daily_news_config.dailynews_group_mode == "whitelist":
        return group_id in group_ids
    return group_id not in group_ids


async def _format_global_settings() -> str:
    stored_values = await runtime_settings.list_scope_values_async("global", None)
    daily_news_enabled = await runtime_settings.get_bool_async(
        "daily_news",
        "enabled",
        daily_news_config.dailynews_enabled,
    )
    sunset_city = await runtime_settings.get_str_async(
        "sunset",
        "default_city",
        sunset_config.sunset_default_city,
    )
    ai_web_search = await runtime_settings.get_bool_async(
        "ai_chat",
        "web_search",
        ai_chat_config.aichat_web_search,
    )
    ai_default_role = await runtime_settings.get_str_async(
        "ai_chat",
        "default_role",
        ai_chat_config.aichat_default_role,
    )
    repeater_threshold = await runtime_settings.get_int_async(
        "repeater",
        "threshold",
        repeater_config.repeater_threshold,
    )
    message_archive_enabled = await runtime_settings.get_bool_async(
        "message_archive",
        "enabled",
        message_archive_config.message_archive_enabled,
    )
    message_archive_retention_days = await runtime_settings.get_int_async(
        "message_archive",
        "retention_days",
        message_archive_config.message_archive_retention_days,
    )

    lines = ["全局运行时配置："]
    lines.append(f"每日新闻：{_on_off(daily_news_enabled)}{_source(stored_values, 'daily_news', 'enabled', '全局配置')}")
    lines.append(f"火烧云城市：{sunset_city}{_source(stored_values, 'sunset', 'default_city', '全局配置')}")
    lines.append(f"AI联网：{_on_off(ai_web_search)}{_source(stored_values, 'ai_chat', 'web_search', '全局配置')}")
    lines.append(f"默认角色：{ai_default_role}{_source(stored_values, 'ai_chat', 'default_role', '全局配置')}")
    repeater_text = "关闭" if repeater_threshold < 2 else str(repeater_threshold)
    lines.append(f"复读阈值：{repeater_text}{_source(stored_values, 'repeater', 'threshold', '全局配置')}")
    lines.append(
        f"群消息记录：{_on_off(message_archive_enabled)}"
        f"{_source(stored_values, 'message_archive', 'enabled', '全局配置')}"
    )
    lines.append(
        f"群消息记录保留：{message_archive_retention_days} 天"
        f"{_source(stored_values, 'message_archive', 'retention_days', '全局配置')}"
    )
    return "\n".join(lines)


def _source(
    stored_values: dict[tuple[str, str], Any],
    namespace: str,
    key: str,
    configured_label: str = "群配置",
) -> str:
    return f"（{configured_label}）" if (namespace, key) in stored_values else "（默认）"


def _require_allowed(
    setting: tuple[str, str],
    allowed_settings: set[tuple[str, str]],
    scope_label: str,
) -> None:
    if setting not in allowed_settings:
        raise SettingsStoreError(f"{scope_label}配置不支持这项设置。")


def _on_off(value: bool) -> str:
    return "开" if value else "关"


def _is_superuser(event: MessageEvent) -> bool:
    user_id = str(event.user_id).strip()
    return user_id in {str(item).strip() for item in driver.config.superusers}


def _parse_config_command(message: str) -> str:
    return re.sub(r"^[.。]配置(?:\s+|$)", "", message, count=1).strip()


def _help_text(*, is_group: bool) -> str:
    if is_group:
        return (
            "群运行时配置命令：\n"
            ".配置 查看\n"
            ".配置 每日新闻 开/关\n"
            ".配置 火烧云城市 上海\n"
            ".配置 AI联网 开/关\n"
            ".配置 默认角色 jarvis\n"
            ".配置 复读阈值 3（小于 2 为关闭）\n"
            ".配置 群记录 开/关\n"
            ".配置 群记录保留 90\n"
            ".配置 重置 火烧云城市"
        )

    return (
        "私聊运行时配置命令：\n"
        ".配置 查看\n"
        ".配置 每日新闻 开/关\n"
        ".配置 火烧云城市 上海\n"
        ".配置 AI联网 开/关\n"
        ".配置 默认角色 jarvis\n"
        ".配置 复读阈值 3（小于 2 为关闭）\n"
        ".配置 群记录 开/关\n"
        ".配置 群记录保留 90\n"
        ".配置 重置 火烧云城市"
    )
