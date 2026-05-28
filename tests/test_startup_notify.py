import nonebot

nonebot.init()

from src.plugins.startup_notify import build_startup_message


def test_build_startup_message_includes_version() -> None:
    assert build_startup_message("abc123") == "茗懿已启动并成功连接 QQ。\n后台版本：abc123"
