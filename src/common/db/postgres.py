from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .mysql import DatabaseError, MySQLConnectionSettings, MySQLHealthCheck


@dataclass(frozen=True)
class PostgresConnectionSettings(MySQLConnectionSettings):
    @classmethod
    def from_config(cls, config: Any) -> "PostgresConnectionSettings":
        return cls(
            host=config.postgres_host.strip(), port=config.postgres_port,
            database=config.postgres_database.strip(), user=config.postgres_user.strip(),
            password=config.postgres_password,
            connect_timeout_seconds=max(1, config.postgres_connect_timeout_seconds),
        )


def is_postgres(config: Any) -> bool:
    return isinstance(config, PostgresConnectionSettings) or getattr(config, "db_backend", "mysql") == "postgres"


def missing_postgres_config_keys(config: Any) -> list[str]:
    settings = config if isinstance(config, PostgresConnectionSettings) else PostgresConnectionSettings.from_config(config)
    return [f"POSTGRES_{key.upper()}" for key in ("host", "database", "user", "password")
            if not str(getattr(settings, key)).strip()]


def connect_postgres(config: Any):
    import psycopg
    from psycopg.rows import dict_row, tuple_row

    settings = config if isinstance(config, PostgresConnectionSettings) else PostgresConnectionSettings.from_config(config)
    missing = missing_postgres_config_keys(settings)
    if missing:
        raise DatabaseError(f"PostgreSQL 配置不完整：{', '.join(missing)}")

    class Connection(psycopg.Connection):
        # Adapt cursor row shape only. SQL remains explicit in each store.
        def cursor(self, *args, dictionary=False, **kwargs):
            kwargs.setdefault("row_factory", dict_row if dictionary else tuple_row)
            return super().cursor(*args, **kwargs)

    try:
        return Connection.connect(
            host=settings.host, port=settings.port, dbname=settings.database,
            user=settings.user, password=settings.password,
            connect_timeout=settings.connect_timeout_seconds,
            options="-c timezone=UTC", application_name="mingyibot",
        )
    except psycopg.Error as exc:
        raise DatabaseError("PostgreSQL 连接失败，请检查地址、凭据和访问规则。") from exc


def check_postgres_connection(config: Any) -> MySQLHealthCheck:
    started = time.monotonic()
    with connect_postgres(config) as connection:
        row = connection.execute("SELECT version(), current_database()").fetchone()
    return MySQLHealthCheck(str(row[0]), str(row[1]), (time.monotonic() - started) * 1000)


def run_postgres_migrations(config: Any, *, namespace: str, migrations=None):
    from .postgres_schema import MIGRATIONS

    if namespace not in MIGRATIONS:
        raise DatabaseError(f"Unknown migration namespace: {namespace}")
    with connect_postgres(config) as connection:
        # Serialize schema initialization across processes and namespaces.
        connection.execute("SELECT pg_advisory_xact_lock(714203981)")
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            namespace VARCHAR(64) NOT NULL, version INT NOT NULL,
            name VARCHAR(128) NOT NULL,
            applied_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(namespace, version))""")
        applied = {row[0] for row in connection.execute(
            "SELECT version FROM schema_migrations WHERE namespace=%s", (namespace,))}
        for version, name, statements in MIGRATIONS[namespace]:
            if version in applied:
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations(namespace,version,name) VALUES (%s,%s,%s)",
                               (namespace, version, name))
