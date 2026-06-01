from src.common.db import MySQLConfig


class RuntimeSettingsConfig(MySQLConfig):
    runtime_settings_cache_seconds: int = 30
