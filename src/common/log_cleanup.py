from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LOG_RETENTION_DAYS = 30
DEFAULT_LOG_CLEANUP_INTERVAL_HOURS = 24


@dataclass(frozen=True)
class LogCleanupConfig:
    log_dir: Path
    pattern: str = "mingyi_*.log"
    retention_days: int = DEFAULT_LOG_RETENTION_DAYS
    interval_hours: int = DEFAULT_LOG_CLEANUP_INTERVAL_HOURS

    @property
    def enabled(self) -> bool:
        return self.retention_days > 0

    @property
    def interval_seconds(self) -> int:
        return max(0, self.interval_hours) * 60 * 60


def cleanup_old_logs(config: LogCleanupConfig, *, now: float | None = None) -> int:
    if not config.enabled or not config.log_dir.exists():
        return 0

    cutoff = (time.time() if now is None else now) - config.retention_days * 24 * 60 * 60
    deleted_count = 0

    for path in config.log_dir.glob(config.pattern):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            deleted_count += 1
        except FileNotFoundError:
            continue

    return deleted_count


async def periodic_log_cleanup(config: LogCleanupConfig, *, logger: Any) -> None:
    if not config.enabled or config.interval_seconds <= 0:
        return

    while True:
        await asyncio.sleep(config.interval_seconds)
        try:
            deleted_count = cleanup_old_logs(config)
        except Exception as exc:  # pragma: no cover - defensive background task guard
            logger.warning("Log cleanup failed: {}", exc)
            continue
        if deleted_count:
            logger.info("Cleaned {} old log files", deleted_count)
