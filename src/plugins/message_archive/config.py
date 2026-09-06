from pydantic import Field
from src.common.db import MySQLConfig


class Config(MySQLConfig):
    message_archive_enabled: bool = False
    message_archive_retention_days: int = 90
    message_archive_queue_size: int = Field(default=1000, ge=1)
    message_archive_workers: int = Field(default=2, ge=1, le=32)
    message_archive_batch_size: int = Field(default=50, ge=1, le=1000)
    message_archive_flush_interval_seconds: float = Field(default=0.5, gt=0)
