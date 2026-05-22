import asyncio
from datetime import datetime, timedelta

from nonebot import get_bots, get_driver, get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata

from .config import Config
from .data_source import DailyNewsError, build_daily_news_image_url


__plugin_meta__ = PluginMetadata(
    name="daily_news",
    description="每天定时向群发送 60s 每日新闻，并支持“今日新闻”手动触发。",
    usage="今日新闻",
    config=Config,
)


config = get_plugin_config(Config)
driver = get_driver()
today_news = on_regex(r"^/?(今日新闻|每日新闻|60s)$", priority=20, block=True)


def _parse_send_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("DAILYNEWS_TIME must use HH:MM format.") from exc

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("DAILYNEWS_TIME must be a valid local time.")

    return hour, minute


def _next_run_at(now: datetime) -> datetime:
    hour, minute = _parse_send_time(config.dailynews_time)
    run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at


def _group_allowed(group_id: int) -> bool:
    group_ids = set(config.dailynews_group_ids)
    if config.dailynews_group_mode == "whitelist":
        return group_id in group_ids
    return group_id not in group_ids


async def _send_to_all_allowed_groups() -> None:
    bots = list(get_bots().values())
    if not bots:
        logger.warning("Daily news skipped: no bot is connected.")
        return

    try:
        message = _build_daily_news_message()
    except DailyNewsError as exc:
        logger.warning("Daily news image message build failed: {}", exc)
        return

    for bot in bots:
        await _send_to_bot_groups(bot, message)


def _build_daily_news_message() -> MessageSegment:
    image_url = build_daily_news_image_url(
        config.dailynews_api_url,
        config.dailynews_image_encoding,
    )
    return MessageSegment.image(image_url)


async def _send_to_bot_groups(bot: Bot, message: MessageSegment) -> None:
    try:
        groups = await bot.get_group_list()
    except Exception as exc:
        logger.warning("Daily news failed to get group list for bot {}: {}", bot.self_id, exc)
        return

    for group in groups:
        group_id = int(group["group_id"])
        if not _group_allowed(group_id):
            continue

        try:
            await bot.send_group_msg(group_id=group_id, message=message)
            await asyncio.sleep(0.5)
        except Exception as exc:
            logger.warning("Daily news failed to send to group {}: {}", group_id, exc)


async def _daily_news_scheduler() -> None:
    while config.dailynews_enabled:
        try:
            run_at = _next_run_at(datetime.now())
        except ValueError as exc:
            logger.error("Daily news scheduler disabled: {}", exc)
            return

        wait_seconds = max((run_at - datetime.now()).total_seconds(), 0)
        logger.info("Daily news next run at {}", run_at.strftime("%Y-%m-%d %H:%M:%S"))
        await asyncio.sleep(wait_seconds)
        await _send_to_all_allowed_groups()


@driver.on_startup
async def start_daily_news_scheduler() -> None:
    if not config.dailynews_enabled:
        return

    asyncio.create_task(_daily_news_scheduler())


@today_news.handle()
async def handle_today_news(event: MessageEvent) -> None:
    try:
        message = _build_daily_news_message()
    except DailyNewsError as exc:
        await today_news.finish(str(exc))

    if isinstance(event, GroupMessageEvent) and not _group_allowed(event.group_id):
        await today_news.finish("当前群不在每日新闻发送范围内。")

    await today_news.finish(message)
