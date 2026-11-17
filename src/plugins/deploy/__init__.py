from __future__ import annotations

import asyncio
import os
import sys

from nonebot import get_driver, logger, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from src.common.background_tasks import shutdown_background_tasks


__plugin_meta__ = PluginMetadata(
    name="deploy",
    description="管理员重启机器人以重新读取配置。",
    usage=".重启",
)


driver = get_driver()
bot_restart = on_regex(r"^[.。]重启$", priority=8, block=True)


@bot_restart.handle()
async def handle_bot_restart(event: MessageEvent) -> None:
    if not _is_superuser(event):
        await bot_restart.finish(MessageSegment.text("只有管理员可以重启机器人。"))

    await bot_restart.send(MessageSegment.text("正在重启机器人并重新读取 .env。"))
    asyncio.create_task(_restart_process())


def _is_superuser(event: MessageEvent) -> bool:
    user_id = str(event.user_id).strip()
    return user_id in {str(item).strip() for item in driver.config.superusers}


async def _restart_process() -> None:
    await asyncio.sleep(1.0)
    logger.warning("Restarting bot process by admin command.")
    await shutdown_background_tasks(timeout_seconds=10.0)
    try:
        os.execv(sys.executable, [sys.executable, *sys.argv])
    except Exception as exc:
        logger.exception("Bot process re-exec failed: {}", exc)
        os._exit(1)
