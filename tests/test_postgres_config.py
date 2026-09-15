import unittest
from unittest.mock import patch
from decimal import Decimal

from src.common.db.config import MySQLConfig
from src.common.db.postgres import connect_postgres, is_postgres
from src.common.db.migrate import encode_row


class PostgresConfigTest(unittest.TestCase):
    def test_old_config_remains_mysql(self):
        self.assertFalse(is_postgres(MySQLConfig(mysql_host="db")))

    def test_invalid_backend_rejected(self):
        with self.assertRaises(ValueError):
            MySQLConfig(db_backend="typo")

    def test_postgres_failure_never_calls_mysql(self):
        with patch("src.common.db.mysql.connect_mysql") as mysql:
            with self.assertRaises(Exception):
                connect_postgres(MySQLConfig(db_backend="postgres"))
            mysql.assert_not_called()

    def test_canonical_decimal_and_text(self):
        self.assertEqual(encode_row([Decimal("1.000"), "中文😀"]), encode_row([Decimal("1"), "中文😀"]))
        self.assertNotEqual(encode_row([None]), encode_row([""]))
        with self.assertRaises(ValueError):
            encode_row(["a\x00b"])
        with self.assertRaises(ValueError):
            encode_row([2**63])
