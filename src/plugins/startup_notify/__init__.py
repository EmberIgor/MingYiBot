import os

from nonebot import get_driver, logger, on_type
from nonebot.adapters.onebot.v11 import Bot
from nonebot.adapters.onebot.v11.event import LifecycleMetaEvent
from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="startup_notify",
    description="OneBot v11 连接成功后通知 SUPERUSERS 当前后台版本。",
    usage="配置 SUPERUSERS 后自动发送启动通知。",
)


driver = get_driver()
startup_event = on_type(LifecycleMetaEvent, priority=1, block=False)
_notified_bot_ids: set[str] = set()


def get_backend_version() -> str:
    return os.getenv("MINGYI_VERSION", "dev").strip() or "dev"


def build_startup_message(version: str) -> str:
    return f"茗懿已启动并成功连接 QQ。\n后台版本：{version}"


def get_superuser_ids() -> list[str]:
    return [str(user_id).strip() for user_id in driver.config.superusers if str(user_id).strip()]


@startup_event.handle()
async def handle_startup_notify(bot: Bot, event: LifecycleMetaEvent) -> None:
    if event.sub_type != "connect":
        return

    bot_id = str(bot.self_id)
    if bot_id in _notified_bot_ids:
        return

    owner_ids = get_superuser_ids()
    if not owner_ids:
        logger.warning("Startup notify skipped: SUPERUSERS is empty.")
        _notified_bot_ids.add(bot_id)
        return

    message = build_startup_message(get_backend_version())
    for owner_id in owner_ids:
        if not owner_id.isdigit():
            logger.warning("Startup notify skipped invalid SUPERUSERS id: {}", owner_id)
            continue

        try:
            await bot.send_private_msg(user_id=int(owner_id), message=message)
        except Exception as exc:
            logger.warning("Startup notify failed to send to superuser {}: {}", owner_id, exc)

    _notified_bot_ids.add(bot_id)
