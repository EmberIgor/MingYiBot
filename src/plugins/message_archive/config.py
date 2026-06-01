from src.common.db import MySQLConfig


class Config(MySQLConfig):
    message_archive_enabled: bool = False
    message_archive_retention_days: int = 90
