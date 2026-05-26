import asyncio
from datetime import date, datetime, timedelta

from nonebot import get_bots, get_driver, get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata

from .config import Config
from .data_source import DailyNewsError, build_daily_news_image_url, fetch_daily_news_date


__plugin_meta__ = PluginMetadata(
    name="daily_news",
    description="每天定时向群发送 60s 每日新闻，并支持“今日新闻”手动触发。",
    usage="今日新闻\n.今日新闻",
    config=Config,
)


config = get_plugin_config(Config)
driver = get_driver()
today_news = on_regex(r"^(?:[.。])?今日新闻$", priority=20, block=True)


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


def _time_at_today(value: str, now: datetime) -> datetime:
    hour, minute = _parse_send_time(value)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _next_run_at(now: datetime) -> datetime:
    run_at = _time_at_today(config.dailynews_time, now)
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at


def _latest_run_at(now: datetime) -> datetime:
    latest = _time_at_today(config.dailynews_latest_time, now)
    if latest < _time_at_today(config.dailynews_time, now):
        latest += timedelta(days=1)
    return latest


def _group_allowed(group_id: int) -> bool:
    group_ids = set(config.dailynews_group_ids)
    if config.dailynews_group_mode == "whitelist":
        return group_id in group_ids
    return group_id not in group_ids


async def _daily_news_is_today() -> bool:
    if not config.dailynews_require_today:
        return True

    news_date = await fetch_daily_news_date(config.dailynews_api_url)
    if news_date == date.today().isoformat():
        return True

    logger.info("Daily news is not updated yet: api date is {}", news_date or "<empty>")
    return False


async def _send_fresh_news_to_all_allowed_groups() -> bool:
    if not await _daily_news_is_today():
        return False

    await _send_to_all_allowed_groups()
    return True


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
        await _retry_send_until_fresh()


async def _retry_send_until_fresh() -> None:
    while True:
        try:
            if await _send_fresh_news_to_all_allowed_groups():
                return
        except DailyNewsError as exc:
            logger.warning("Daily news freshness check failed: {}", exc)

        now = datetime.now()
        try:
            latest = _latest_run_at(now)
        except ValueError as exc:
            logger.error("Daily news scheduler disabled: {}", exc)
            return

        if now >= latest:
            logger.warning("Daily news skipped: still not updated before {}", config.dailynews_latest_time)
            return

        retry_seconds = max(config.dailynews_retry_interval_minutes, 1) * 60
        wait_seconds = min(retry_seconds, max((latest - now).total_seconds(), 0))
        logger.info("Daily news will retry in {} seconds", int(wait_seconds))
        await asyncio.sleep(wait_seconds)


@driver.on_startup
async def start_daily_news_scheduler() -> None:
    if not config.dailynews_enabled:
        return

    asyncio.create_task(_daily_news_scheduler())


@today_news.handle()
async def handle_today_news(event: MessageEvent) -> None:
    try:
        if not await _daily_news_is_today():
            await today_news.finish("今日新闻还没有更新，请稍后再试。")
    except DailyNewsError as exc:
        logger.warning("Daily news command freshness check failed: {}", exc)
        await today_news.finish(str(exc))

    try:
        message = _build_daily_news_message()
    except DailyNewsError as exc:
        logger.warning("Daily news command message build failed: {}", exc)
        await today_news.finish(str(exc))

    if isinstance(event, GroupMessageEvent) and not _group_allowed(event.group_id):
        await today_news.finish("当前群不在每日新闻发送范围内。")

    await today_news.finish(message)
