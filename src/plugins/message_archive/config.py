from src.common.db import MySQLConfig


class Config(MySQLConfig):
    message_archive_enabled: bool = False
    message_archive_retention_days: int = 90
    message_archive_hotword_limit: int = 12
    message_archive_query_limit: int = 5000
