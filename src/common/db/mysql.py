from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable


class DatabaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class MySQLConnectionSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    connect_timeout_seconds: int

    @classmethod
    def from_config(cls, config: Any) -> "MySQLConnectionSettings":
        return cls(
            host=str(getattr(config, "mysql_host", "")).strip(),
            port=int(getattr(config, "mysql_port", 3306)),
            database=str(getattr(config, "mysql_database", "")).strip(),
            user=str(getattr(config, "mysql_user", "")).strip(),
            password=str(getattr(config, "mysql_password", "")),
            connect_timeout_seconds=max(
                1,
                int(getattr(config, "mysql_connect_timeout_seconds", 5)),
            ),
        )


@dataclass(frozen=True)
class MySQLHealthCheck:
    version: str
    database: str
    elapsed_ms: float


@dataclass(frozen=True)
class MySQLMigration:
    version: int
    name: str
    statements: tuple[str, ...]


def missing_mysql_config_keys(config: Any) -> list[str]:
    if isinstance(config, MySQLConnectionSettings):
        host = config.host
        user = config.user
        password = config.password
        database = config.database
    else:
        host = str(getattr(config, "mysql_host", "")).strip()
        user = str(getattr(config, "mysql_user", "")).strip()
        password = str(getattr(config, "mysql_password", ""))
        database = str(getattr(config, "mysql_database", "")).strip()
    required_values = {
        "MYSQL_HOST": host,
        "MYSQL_USER": user,
        "MYSQL_PASSWORD": password,
        "MYSQL_DATABASE": database,
    }
    return [key for key, value in required_values.items() if not str(value).strip()]


def connect_mysql(config: Any):
    try:
        settings = _settings(config)
    except (TypeError, ValueError) as exc:
        raise DatabaseError(str(exc)) from exc
    missing_keys = missing_mysql_config_keys(settings)
    if missing_keys:
        raise DatabaseError(f"MySQL 配置不完整：{', '.join(missing_keys)}")

    try:
        import mysql.connector
    except ImportError as exc:
        raise DatabaseError("缺少 mysql-connector-python 依赖。") from exc

    return mysql.connector.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        connection_timeout=settings.connect_timeout_seconds,
    )


def check_mysql_connection(config: Any) -> MySQLHealthCheck:
    started_at = time.monotonic()
    try:
        connection = connect_mysql(config)
    except Exception as exc:
        raise _database_error(exc) from exc

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION(), DATABASE()")
            row = cursor.fetchone()
    except Exception as exc:
        raise _database_error(exc) from exc
    finally:
        connection.close()

    if not row:
        raise DatabaseError("数据库没有返回测试结果。")

    elapsed_ms = (time.monotonic() - started_at) * 1000
    return MySQLHealthCheck(version=str(row[0]), database=str(row[1]), elapsed_ms=elapsed_ms)


def run_mysql_migrations(
    config: Any,
    *,
    namespace: str,
    migrations: Iterable[MySQLMigration],
) -> list[MySQLMigration]:
    namespace = namespace.strip()
    if not namespace:
        raise DatabaseError("MySQL migration namespace cannot be empty.")

    try:
        with connect_mysql(config) as connection:
            with connection.cursor() as cursor:
                _ensure_migrations_table(cursor)
                applied_versions = _applied_versions(cursor, namespace)
                applied_migrations: list[MySQLMigration] = []
                for migration in sorted(migrations, key=lambda item: item.version):
                    if migration.version in applied_versions:
                        continue

                    for statement in migration.statements:
                        cursor.execute(statement)
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (namespace, version, name)
                        VALUES (%s, %s, %s)
                        """,
                        (namespace, migration.version, migration.name),
                    )
                    connection.commit()
                    applied_versions.add(migration.version)
                    applied_migrations.append(migration)
    except Exception as exc:
        raise _database_error(exc) from exc

    return applied_migrations


def _settings(config: Any) -> MySQLConnectionSettings:
    if isinstance(config, MySQLConnectionSettings):
        return config
    return MySQLConnectionSettings.from_config(config)


def _ensure_migrations_table(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          namespace VARCHAR(64) NOT NULL,
          version INT NOT NULL,
          name VARCHAR(128) NOT NULL,
          applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (namespace, version)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """
    )


def _applied_versions(cursor: Any, namespace: str) -> set[int]:
    cursor.execute(
        "SELECT version FROM schema_migrations WHERE namespace = %s",
        (namespace,),
    )
    return {int(row[0]) for row in cursor.fetchall()}


def _database_error(exc: Exception) -> DatabaseError:
    if isinstance(exc, DatabaseError):
        return exc
    return DatabaseError(str(exc))
