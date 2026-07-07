import asyncio
import os
import re
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.log import logger

from src.common.log_cleanup import LogCleanupConfig, cleanup_old_logs, periodic_log_cleanup


CONTAINER_ENV_FILE = Path("/app/.env")
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "mingyi_{time:YYYY-MM-DD}.log"
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LOG_CLEANUP_CONFIG = LogCleanupConfig(log_dir=LOG_DIR)
_log_cleanup_task: asyncio.Task[None] | None = None


def load_container_env_file(path: Path = CONTAINER_ENV_FILE) -> None:
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not ENV_KEY_PATTERN.match(key):
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ[key] = value


def configure_file_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(
        LOG_FILE,
        rotation="00:00",
        retention=f"{LOG_CLEANUP_CONFIG.retention_days} days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )


async def start_log_cleanup() -> None:
    global _log_cleanup_task

    deleted_count = cleanup_old_logs(LOG_CLEANUP_CONFIG)
    if deleted_count:
        logger.info("Cleaned {} old log files on startup", deleted_count)

    if _log_cleanup_task is None or _log_cleanup_task.done():
        _log_cleanup_task = asyncio.create_task(periodic_log_cleanup(LOG_CLEANUP_CONFIG, logger=logger))


load_container_env_file()
nonebot.init()
configure_file_logging()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)
driver.on_startup(start_log_cleanup)

nonebot.load_from_toml("pyproject.toml")


if __name__ == "__main__":
    nonebot.run()
