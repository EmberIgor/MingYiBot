from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

import src.plugins.ping as ping


class PingPerformanceTest(unittest.TestCase):
    def test_build_performance_report_includes_latency_processing_and_event_time(self) -> None:
        event = SimpleNamespace(time=1_700_000_000)

        with patch.object(ping.time, "perf_counter", return_value=12.345):
            report = ping.build_performance_report(event, started_at=12.0, received_at=1_700_000_001.25)

        self.assertIn("性能测试结果", report)
        self.assertIn("事件延迟：1250 ms", report)
        self.assertIn("处理耗时：345 ms", report)
        self.assertIn("事件时间：", report)
        self.assertIn("说明：事件延迟受平台、OneBot、网络、队列和宿主机时钟影响。", report)

    def test_build_performance_report_handles_missing_event_time(self) -> None:
        event = SimpleNamespace()

        with patch.object(ping.time, "perf_counter", return_value=10.0):
            report = ping.build_performance_report(event, started_at=9.95, received_at=1_700_000_001.25)

        self.assertIn("事件延迟：不可用", report)
        self.assertIn("事件时间：不可用", report)
        self.assertIn("处理耗时：50 ms", report)

    def test_build_performance_report_handles_invalid_event_time(self) -> None:
        event = SimpleNamespace(time="not-a-timestamp")

        with patch.object(ping.time, "perf_counter", return_value=10.0):
            report = ping.build_performance_report(event, started_at=9.95, received_at=1_700_000_001.25)

        self.assertIn("事件延迟：不可用", report)
        self.assertIn("事件时间：不可用", report)

    def test_build_performance_report_clamps_future_event_latency_to_zero(self) -> None:
        event = SimpleNamespace(time=1_700_000_002)

        with patch.object(ping.time, "perf_counter", return_value=10.0):
            report = ping.build_performance_report(event, started_at=10.0, received_at=1_700_000_001.25)

        self.assertIn("事件延迟：0 ms", report)

    def test_is_superuser_matches_driver_superusers(self) -> None:
        original_driver = ping.driver
        ping.driver = SimpleNamespace(config=SimpleNamespace(superusers={"123456"}))
        try:
            self.assertTrue(ping._is_superuser(SimpleNamespace(user_id=123456)))
            self.assertFalse(ping._is_superuser(SimpleNamespace(user_id=654321)))
        finally:
            ping.driver = original_driver


if __name__ == "__main__":
    unittest.main()
