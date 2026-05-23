from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.log import logger


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "mingyi_{time:YYYY-MM-DD}.log"


def configure_file_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(
        LOG_FILE,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )


nonebot.init()
configure_file_logging()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_from_toml("pyproject.toml")


if __name__ == "__main__":
    nonebot.run()
