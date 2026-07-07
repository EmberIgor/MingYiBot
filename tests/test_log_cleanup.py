from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from src.common.log_cleanup import LogCleanupConfig, cleanup_old_logs


class LogCleanupTest(unittest.TestCase):
    def test_cleanup_old_logs_keeps_recent_and_unmatched_files(self) -> None:
        now = time.time()

        with tempfile.TemporaryDirectory() as tmp_dir:
            log_dir = Path(tmp_dir)
            old_log = log_dir / "mingyi_2026-01-01.log"
            recent_log = log_dir / "mingyi_2026-07-08.log"
            other_file = log_dir / "notes.txt"

            old_log.write_text("old", encoding="utf-8")
            recent_log.write_text("recent", encoding="utf-8")
            other_file.write_text("keep", encoding="utf-8")
            old_timestamp = now - 31 * 24 * 60 * 60
            recent_timestamp = now - 2 * 24 * 60 * 60

            for path, timestamp in (
                (old_log, old_timestamp),
                (recent_log, recent_timestamp),
                (other_file, old_timestamp),
            ):
                os.utime(path, (timestamp, timestamp))

            deleted_count = cleanup_old_logs(LogCleanupConfig(log_dir=log_dir), now=now)

            self.assertEqual(deleted_count, 1)
            self.assertFalse(old_log.exists())
            self.assertTrue(recent_log.exists())
            self.assertTrue(other_file.exists())


if __name__ == "__main__":
    unittest.main()
