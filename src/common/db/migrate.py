"""Offline full-fidelity migration. Run: python -m src.common.db.migrate --help."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .config import MySQLConfig
from .mysql import connect_mysql
from .postgres import connect_postgres, run_postgres_migrations
from .postgres_schema import MIGRATIONS

TABLES = ("ai_chat_memories", "group_message_records", "runtime_settings")
BATCH_SIZE = 500


@contextmanager
def source_cursor(source):
    cursor = source.cursor()
    try:
        yield cursor
    finally:
        # A rejected target or invalid source value may leave unread MySQL rows.
        # Drain them so cursor.close() does not hide the original failure.
        source.consume_results()
        cursor.close()


def read_config(path: str) -> MySQLConfig:
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip().lower()] = value
    return MySQLConfig(**values)


def canonical(value):
    if isinstance(value, datetime):
        return {"datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, Decimal):
        return {"decimal": format(value.normalize(), "f")}
    if value is None or isinstance(value, (str, int)):
        return value
    raise ValueError(f"Unsupported value type: {type(value).__name__}")


def encode_row(row, *, allow_nul_indexes=()):
    for index, value in enumerate(row):
        if isinstance(value, str):
            if "\x00" in value and index not in allow_nul_indexes:
                raise ValueError("PostgreSQL cannot preserve a NUL character")
            value.encode("utf-8", errors="strict")
        if isinstance(value, int) and not -(2**63) <= value < 2**63:
            raise ValueError("Integer outside PostgreSQL bigint range")
    return (json.dumps([canonical(v) for v in row], ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def binary_indexes(table, columns):
    return (columns.index("sender_card"),) if table == "group_message_records" else ()


def logical_row(row, indexes):
    values = list(row)
    for index in indexes:
        if isinstance(values[index], (bytes, memoryview)):
            values[index] = bytes(values[index]).decode("utf-8", errors="strict")
    return values


def postgres_row(row, indexes):
    values = list(row)
    for index in indexes:
        if isinstance(values[index], str):
            values[index] = values[index].encode("utf-8", errors="strict")
    return values


def transfer(source, target, *, copy=False, backup=None):
    """Compare every value in one source snapshot and one target transaction."""
    from psycopg import sql

    report = {}
    for table in TABLES:
        with source_cursor(source) as src, target.cursor() as dst:
            src.execute(f"SELECT * FROM `{table}` ORDER BY id")
            columns = list(src.column_names)
            indexes = binary_indexes(table, columns)
            dst.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(sql.Identifier(table)))
            if set(columns) != {d.name for d in dst.description}:
                raise ValueError(f"Column mismatch: {table}")
            column_sql = sql.SQL(",").join(map(sql.Identifier, columns))
            if copy:
                dst.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
                if dst.fetchone()[0]:
                    raise ValueError(f"Target must be empty: {table}")
            digest = hashlib.sha256()
            count = 0
            while rows := src.fetchmany(BATCH_SIZE):
                for row in rows:
                    try:
                        encoded = encode_row(row, allow_nul_indexes=indexes)
                    except (ValueError, UnicodeError) as exc:
                        raise ValueError(f"Unsupported data in {table}, id={row[columns.index('id')]}") from exc
                    digest.update(encoded)
                    if backup:
                        backup.write(json.dumps({"table": table, "columns": columns, "row": [canonical(v) for v in row]}, ensure_ascii=False) + "\n")
                if copy:
                    dst.executemany(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table), column_sql,
                        sql.SQL(",").join(sql.Placeholder() for _ in columns)),
                        [postgres_row(row, indexes) for row in rows])
                count += len(rows)
            dst.execute(sql.SQL("SELECT {} FROM {} ORDER BY id").format(column_sql, sql.Identifier(table)))
            target_digest = hashlib.sha256()
            target_count = 0
            while rows := dst.fetchmany(BATCH_SIZE):
                for row in rows:
                    target_digest.update(encode_row(logical_row(row, indexes), allow_nul_indexes=indexes))
                target_count += len(rows)
            if count != target_count or digest.digest() != target_digest.digest():
                raise ValueError(f"Data verification failed: {table}")
            if copy:
                dst.execute(sql.SQL("SELECT COALESCE(MAX(id),0) FROM {}").format(sql.Identifier(table)))
                next_id = max(1, dst.fetchone()[0] + 1)
                # ALTER identity restart is transactional, unlike setval().
                dst.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN id RESTART WITH {}").format(
                    sql.Identifier(table), sql.Literal(next_id)))
            report[table] = {"rows": count, "sha256": digest.hexdigest()}
    return report


def precheck(source):
    report = {}
    with source_cursor(source) as cursor:
        cursor.execute("SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
        engines = dict(cursor.fetchall())
        unexpected = set(engines) - set(TABLES) - {"schema_migrations"}
        if unexpected:
            raise ValueError(f"Unplanned source tables: {sorted(unexpected)}")
        for table in TABLES:
            if engines.get(table) != "InnoDB":
                raise ValueError(f"Missing table or nontransactional engine: {table}")
            cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                           "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
                           "AND DATA_TYPE IN ('datetime','timestamp','date')", (table,))
            for (column,) in cursor.fetchall():
                quoted = column.replace("`", "``")
                cursor.execute(f"SELECT COUNT(*) FROM `{table}` WHERE "
                               f"YEAR(`{quoted}`)=0 OR MONTH(`{quoted}`)=0 OR DAY(`{quoted}`)=0")
                if cursor.fetchone()[0]:
                    raise ValueError(f"Zero date cannot be preserved: {table}.{column}")
            cursor.execute(f"SELECT * FROM `{table}` ORDER BY id")
            indexes = binary_indexes(table, list(cursor.column_names))
            count = 0
            while rows := cursor.fetchmany(BATCH_SIZE):
                for row in rows:
                    encode_row(row, allow_nul_indexes=indexes)
                    count += 1
            report[table] = count
    return report


def migrate(config, mode, *, backup_path=None):
    if mode == "import":
        for namespace in MIGRATIONS:
            run_postgres_migrations(config, namespace=namespace)
    source = connect_mysql(config)
    try:
        source.start_transaction(isolation_level="REPEATABLE READ", consistent_snapshot=True, readonly=True)
        precheck_report = precheck(source)
        if mode == "precheck":
            with connect_postgres(config) as target:
                version = target.execute("SELECT version()").fetchone()[0]
            return {"source_rows": precheck_report, "target_version": version}
        with connect_postgres(config) as target:
            target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            if mode == "import":
                if not backup_path:
                    raise ValueError("A new backup path is required")
                # Prevent concurrent imports and writes throughout the final comparison.
                target.execute("LOCK TABLE ai_chat_memories, group_message_records, runtime_settings IN ACCESS EXCLUSIVE MODE")
                fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as raw, gzip.open(raw, "wt", encoding="utf-8") as backup:
                    return transfer(source, target, copy=True, backup=backup)
            return transfer(source, target)
    finally:
        source.rollback()
        source.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("precheck", "import", "verify"))
    parser.add_argument("--config", required=True, help="Protected env file containing both database connections")
    parser.add_argument("--report", required=True)
    parser.add_argument("--backup", help="New gzip JSONL snapshot path for import")
    parser.add_argument("--source-stopped", action="store_true", help="Operator confirms all bot writers are stopped")
    args = parser.parse_args()
    if args.mode == "import" and (not args.source_stopped or not args.backup):
        parser.error("import requires --source-stopped and --backup")
    # Never overwrite an existing acceptance report.
    fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as report_file:
        try:
            report = migrate(read_config(args.config), args.mode, backup_path=args.backup)
            json.dump({"status": "verified", "mode": args.mode, "tables": report}, report_file, ensure_ascii=False, indent=2)
        except Exception as exc:
            # Driver errors can include passwords or message content. Do not print them.
            json.dump({"status": "failed", "error_type": type(exc).__name__}, report_file)
            raise SystemExit(f"Migration failed ({type(exc).__name__}); configuration was not switched.") from None
    print(f"{args.mode}: verified; report saved")


if __name__ == "__main__":
    main()
