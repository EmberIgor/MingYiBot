import asyncio
import re
from datetime import datetime, timedelta

from nonebot import get_bots, get_driver, get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from src.common.settings import get_runtime_settings_store

from .config import Config
from .data_source import (
    SunsetError,
    build_sunset_alert,
    build_sunset_report,
    fetch_sunset_events,
)


__plugin_meta__ = PluginMetadata(
    name="sunset",
    description="查询指定地点两日内火烧云分析信息。",
    usage="sun 上海\n.sun 上海\n火烧云 北京\n.火烧云 北京",
    config=Config,
)


config = get_plugin_config(Config)
runtime_settings = get_runtime_settings_store()
driver = get_driver()
sun_command = on_regex(r"^(?:[.。])?(?:sun|火烧云)(?:\s+|$)(.*)$", priority=20, block=True)


@sun_command.handle()
async def handle_sun(event: MessageEvent) -> None:
    location = _extract_location(event.get_plaintext())
    if not location:
        group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
        location = await runtime_settings.get_str_async(
            "sunset",
            "default_city",
            config.sunset_default_city,
            group_id=group_id,
        )

    try:
        report = await build_sunset_report(
            location=location,
            api_url=config.sunset_api_url,
            model=config.sunset_model,
            timeout_seconds=config.sunset_timeout_seconds,
        )
    except SunsetError as exc:
        logger.warning("Sunset command failed for location {}: {}", location, exc)
        await sun_command.finish(str(exc))

    await sun_command.finish(MessageSegment.text(report))


def _extract_location(message: str) -> str:
    return re.sub(r"^(?:[.。])?(?:sun|火烧云)(?:\s+|$)", "", message, count=1).strip()


def _parse_notify_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("SUNSET_NOTIFY_TIMES must use HH:MM format.") from exc

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("SUNSET_NOTIFY_TIMES must contain valid local times.")

    return hour, minute


def _next_notify_at(now: datetime) -> datetime:
    notify_times = sorted(_parse_notify_time(value) for value in config.sunset_notify_times)
    if not notify_times:
        raise ValueError("SUNSET_NOTIFY_TIMES cannot be empty.")

    today_candidates = [
        now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        for hour, minute in notify_times
    ]
    future_candidates = [candidate for candidate in today_candidates if candidate > now]
    if future_candidates:
        return min(future_candidates)

    first_hour, first_minute = notify_times[0]
    return (now + timedelta(days=1)).replace(
        hour=first_hour,
        minute=first_minute,
        second=0,
        microsecond=0,
    )


def _owner_ids() -> list[str]:
    configured_ids = [str(owner_id).strip() for owner_id in config.sunset_owner_ids]
    owner_ids = configured_ids or [str(owner_id).strip() for owner_id in driver.config.superusers]
    return [owner_id for owner_id in owner_ids if owner_id]


async def _send_private_message(bot: Bot, owner_id: str, message: str) -> None:
    if not owner_id.isdigit():
        logger.warning("Sunset alert skipped invalid owner id: {}", owner_id)
        return

    try:
        await bot.send_private_msg(user_id=int(owner_id), message=message)
    except Exception as exc:
        logger.warning("Sunset alert failed to send to owner {}: {}", owner_id, exc)


async def _run_sunset_notify() -> None:
    bots = list(get_bots().values())
    if not bots:
        logger.warning("Sunset alert skipped: no bot is connected.")
        return

    owner_ids = _owner_ids()
    if not owner_ids:
        logger.warning("Sunset alert skipped: no owner configured. Set SUNSET_OWNER_IDS or SUPERUSERS.")
        return

    try:
        responses = await fetch_sunset_events(
            location=config.sunset_default_city,
            api_url=config.sunset_api_url,
            model=config.sunset_model,
            timeout_seconds=config.sunset_timeout_seconds,
        )
    except SunsetError as exc:
        logger.warning("Sunset alert query failed: {}", exc)
        return

    alert = build_sunset_alert(responses, config.sunset_notify_threshold)
    if not alert:
        logger.info(
            "Sunset alert checked {}: no event reaches {}.",
            config.sunset_default_city,
            config.sunset_notify_threshold,
        )
        return

    bot = bots[0]
    for owner_id in owner_ids:
        await _send_private_message(bot, owner_id, alert)


async def _sunset_notify_scheduler() -> None:
    while config.sunset_notify_enabled:
        try:
            run_at = _next_notify_at(datetime.now())
        except ValueError as exc:
            logger.error("Sunset alert scheduler disabled: {}", exc)
            return

        wait_seconds = max((run_at - datetime.now()).total_seconds(), 0)
        logger.info("Sunset alert next run at {}", run_at.strftime("%Y-%m-%d %H:%M:%S"))
        await asyncio.sleep(wait_seconds)
        await _run_sunset_notify()


@driver.on_startup
async def start_sunset_notify_scheduler() -> None:
    if not config.sunset_notify_enabled:
        return

    asyncio.create_task(_sunset_notify_scheduler())
