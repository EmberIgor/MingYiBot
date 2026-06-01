from __future__ import annotations

import asyncio

from nonebot import get_driver, get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from src.common.db import DatabaseError, check_mysql_connection, missing_mysql_config_keys

from .config import Config


__plugin_meta__ = PluginMetadata(
    name="mysql_test",
    description="管理员测试 MySQL 数据库连通性。",
    usage=".数据库测试\n.mysql测试\n.db测试",
    config=Config,
)


config = get_plugin_config(Config)
driver = get_driver()
mysql_test = on_regex(r"^[.。](?:数据库测试|mysql测试|db测试)$", priority=8, block=True)


@mysql_test.handle()
async def handle_mysql_test(event: MessageEvent) -> None:
    if not _is_superuser(event):
        await mysql_test.finish(MessageSegment.text("只有管理员可以测试数据库连接。"))

    missing_keys = _missing_config_keys()
    if missing_keys:
        await mysql_test.finish(
            MessageSegment.text(f"MySQL 配置不完整，请先在 .env 中填写：{', '.join(missing_keys)}")
        )

    try:
        result = await asyncio.to_thread(_test_mysql_connection)
    except MySQLTestError as exc:
        logger.warning("MySQL connection test failed: {}", exc)
        await mysql_test.finish(MessageSegment.text(f"MySQL 连接失败：{exc}"))

    await mysql_test.finish(
        MessageSegment.text(
            "MySQL 连接成功\n"
            f"地址：{config.mysql_host}:{config.mysql_port}\n"
            f"数据库：{result.database}\n"
            f"版本：{result.version}\n"
            f"延迟：{result.elapsed_ms:.0f} ms"
        )
    )


def _is_superuser(event: MessageEvent) -> bool:
    user_id = str(event.user_id).strip()
    return user_id in {str(item).strip() for item in driver.config.superusers}


def _missing_config_keys() -> list[str]:
    return missing_mysql_config_keys(config)


def _test_mysql_connection():
    try:
        return check_mysql_connection(config)
    except DatabaseError as exc:
        raise MySQLTestError(str(exc)) from exc


class MySQLTestError(RuntimeError):
    pass
