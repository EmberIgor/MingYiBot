import asyncio
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()
from src.plugins.sunset import data_source as ds
from src.plugins.sunset import sources as sky

NOW = datetime(2026, 11, 17, 10, 40, tzinfo=sky.TZ)
ROOT = Path(__file__).resolve().parents[1]


def good():
    return dict(
        source=sky.LOCAL,
        date="2026-11-17",
        event="set",
        event_time="2026-11-17T17:00:00+08:00",
        city="北京",
        status="valid",
        score=75,
        quality=None,
        probability=None,
        cloud_evidence=dict(mid=40, high=20, low=10),
        weather=dict(precipitation=0, rain_near=0, rain_early=0, pop_max=0),
        valid_until="2026-11-17T11:00:00+08:00",
        errors=[],
    )


class NotificationTests(unittest.TestCase):
    def test_cache_rechecks_expiry_instead_of_reusing_values(self):
        raw = json.loads((ROOT / "tests/fixtures/sky/glow_beijing.json").read_text())
        raw["prediction"]["cloudglowTransitions"] = []
        raw["prediction"]["qualityValidUntil"] = (
            NOW + timedelta(seconds=30)
        ).isoformat()
        bundle = dict(
            source=sky.GLOW,
            collected_at=NOW.isoformat(),
            entries=[dict(raw=raw, day="2026-11-17", spot="beijing")],
        )
        parsed = sky.normalize_bundle(bundle, NOW + timedelta(minutes=1))
        self.assertIsNone(parsed[0]["quality"])
        self.assertEqual(parsed[0]["probability"], 49)

    def test_strength_is_not_burn_grade_and_invalid_fails_closed(self):
        events = [("set_1", dict(city="北京", forecasts=[good()], errors=[]))]
        self.assertTrue(ds.build_sunset_alert(events, "中烧", now=NOW))
        for threshold in ("大烧", "garbage", "", "中烧或者不烧"):
            self.assertEqual(ds.build_sunset_alert(events, threshold, now=NOW), "")
        self.assertNotIn("可能达到中烧", ds.build_sunset_alert(events, "中烧", now=NOW))

    def test_passed_expired_missing_and_physical_guards_suppress(self):
        for updates in [
            dict(event_time="2026-11-17T07:00:00+08:00"),
            dict(status="passed"),
            dict(score=None),
            dict(valid_until="2026-11-17T10:00:00+08:00"),
            dict(cloud_evidence=dict(mid=0, high=0, low=0)),
            dict(weather=dict(precipitation=1, rain_near=0, rain_early=0, pop_max=0)),
            dict(weather=dict(precipitation=None)),
            dict(cloud_evidence=dict(mid=60, high=30, low=90)),
        ]:
            f = dict(good(), **updates)
            self.assertEqual(
                ds.build_sunset_alert(
                    [("set_1", dict(city="北京", forecasts=[f], errors=[]))],
                    "中烧",
                    now=NOW,
                ),
                "",
            )

    def test_alert_omits_other_sources_already_passed_minute(self):
        future = good()
        past = dict(good(), source=sky.GLOW, event_time="2026-11-17T10:39:00+08:00")
        alert = ds.build_sunset_alert(
            [("set_1", dict(city="北京", forecasts=[future, past], errors=[]))], now=NOW
        )
        self.assertNotIn("10:39", alert)

    def test_glow_has_its_own_quality_probability_and_freshness_guards(self):
        raw = json.loads((ROOT / "tests/fixtures/sky/glow_beijing.json").read_text())
        f = sky.normalize_glow(raw, "2026-11-17", "beijing", NOW)
        f["quality"] = 75
        self.assertEqual(ds.opportunity_strength(f, NOW), 75)
        for change in [
            dict(probability=0),
            dict(probability=None),
            dict(action_state="unavailable"),
            dict(source_status="no_opportunity"),
            dict(freshness={}),
            dict(action_valid_until="2026-11-17T10:00:00+08:00"),
            dict(
                weather=dict(
                    precipitationRateMmH=0, isPrecipitating=True, blocksSunset=False
                )
            ),
        ]:
            self.assertEqual(ds.opportunity_strength(dict(f, **change), NOW), 0)

    def test_remaining_source_report_and_alert_include_unknown_notice(self):
        events = [
            (
                "set_1",
                dict(city="北京", forecasts=[good()], errors=["Glow Sunset: http_429"]),
            )
        ]
        report = ds.format_sunset_report(events, now=NOW)
        self.assertIn("75/100", report)
        self.assertIn("启发式", report)
        self.assertIn("未知", report)
        self.assertIn("2026-11-17", report)
        self.assertIn("Open-Meteo", report)
        self.assertIn("未知", ds.build_sunset_alert(events, now=NOW))


class AsyncCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        ds._cache.clear()
        ds._inflight.clear()

    async def test_source_failure_does_not_hide_other_and_cache_revalidates(self):
        raw = json.loads((ROOT / "tests/fixtures/sky/glow_beijing.json").read_text())
        bundle = dict(
            source=sky.GLOW,
            collected_at=NOW.isoformat(),
            entries=[dict(raw=raw, day="2026-11-17", spot="beijing")],
            errors=[],
        )
        with (
            patch.object(
                ds,
                "_run_worker",
                AsyncMock(side_effect=[bundle, RuntimeError("http_429")]),
            ),
            patch.object(ds, "_now", return_value=NOW),
        ):
            result = await ds.fetch_sunset_events("北京")
        self.assertEqual(result[1][1]["forecasts"][0]["quality"], 54)
        self.assertIn("未知", ds.format_sunset_report(result, now=NOW))
        later = NOW + timedelta(minutes=1)
        with (
            patch.object(
                ds, "_run_worker", AsyncMock(side_effect=RuntimeError("offline"))
            ),
            patch.object(ds, "_now", return_value=later),
        ):
            repeated = await ds.fetch_sunset_events("北京")
        self.assertEqual(repeated[1][1]["forecasts"][0]["quality"], 54)
        self.assertEqual(len(ds._cache), 1)

    async def test_whole_collection_budget_and_city_concurrency_cap(self):
        async def slow(*args):
            await asyncio.sleep(2)

        with (
            patch.object(ds, "COLLECTION_BUDGET", 0.03),
            patch.object(ds, "_run_worker", slow),
        ):
            with self.assertRaises(ds.SunsetError):
                await ds.fetch_sunset_events("北京")
        self.assertFalse(ds._inflight)
        with patch.object(ds, "_run_worker", slow):
            first = asyncio.create_task(ds.fetch_sunset_events("北京"))
            second = asyncio.create_task(ds.fetch_sunset_events("上海"))
            await asyncio.sleep(0.01)
            with self.assertRaises(ds.SunsetError):
                await ds.fetch_sunset_events("广州")
            first.cancel()
            second.cancel()
            await asyncio.gather(first, second, return_exceptions=True)
        self.assertFalse(ds._inflight)

    async def test_one_cancelled_waiter_does_not_cancel_shared_fetch(self):
        async def worker(source, *args):
            await asyncio.sleep(0.02)
            return dict(
                source=sky.GLOW if source == "glow" else sky.LOCAL, errors=["offline"]
            )

        with patch.object(ds, "_run_worker", worker):
            first = asyncio.create_task(ds.fetch_sunset_events("北京"))
            second = asyncio.create_task(ds.fetch_sunset_events("北京"))
            await asyncio.sleep(0.005)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            self.assertEqual(len(await second), 4)
        self.assertFalse(ds._inflight)

    async def test_timeout_reaps_worker_grandchildren(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "survived"
            child = f"import time,pathlib; time.sleep(.4); pathlib.Path({str(marker)!r}).write_text('leak')"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(20)"
            with self.assertRaises(TimeoutError):
                await ds._run_process([ds.sys.executable, "-c", parent], 0.15)
            await asyncio.sleep(0.5)
            self.assertFalse(marker.exists())

    async def test_repeated_city_deduplicates_and_timeout_is_hard(self):
        calls = []

        async def worker(source, city, timeout):
            calls.append(source)
            await asyncio.sleep(0.01)
            return dict(
                source=sky.GLOW if source == "glow" else sky.LOCAL, errors=["offline"]
            )

        with patch.object(ds, "_run_worker", worker):
            await asyncio.gather(
                ds.fetch_sunset_events("北京"), ds.fetch_sunset_events("北京市")
            )
        self.assertEqual(calls, ["glow", "local"])
        started = asyncio.get_running_loop().time()
        with self.assertRaises(TimeoutError):
            await ds._run_process(
                [ds.sys.executable, "-c", "import time; time.sleep(20)"], 0.05
            )
        self.assertLess(asyncio.get_running_loop().time() - started, 1)


class PluginIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_uses_global_city_and_owner_path(self):
        import src.plugins.sunset as plugin

        settings = AsyncMock()
        settings.get_str_async.return_value = "上海"
        response = [
            (
                "set_1",
                dict(city="上海", date="2026-11-17", forecasts=[good()], errors=[]),
            )
        ]
        with (
            patch.object(plugin, "get_bots", return_value={"1": object()}),
            patch.object(plugin, "_owner_ids", return_value=["123"]),
            patch.object(plugin, "runtime_settings", settings),
            patch.object(
                plugin, "fetch_sunset_events", AsyncMock(return_value=response)
            ) as fetch,
            patch.object(plugin, "build_sunset_alert", return_value="alert"),
            patch.object(plugin, "_send_private_message", AsyncMock()) as send,
        ):
            await plugin._run_sunset_notify()
        self.assertEqual(fetch.call_args.kwargs["location"], "上海")
        self.assertEqual(send.await_count, 1)

    def test_commands_and_shanghai_schedule(self):
        from datetime import timezone

        import src.plugins.sunset as plugin

        for text in ("sun 上海", ".sun 上海", "。火烧云 上海", "火烧云 上海"):
            self.assertEqual(plugin._extract_location(text), "上海")
        with patch.object(plugin.config, "sunset_notify_times", ["09:00", "21:00"]):
            run = plugin._next_notify_at(datetime(2026, 11, 17, 2, tzinfo=timezone.utc))
        self.assertEqual(run.hour, 21)
        self.assertEqual(str(run.tzinfo), "Asia/Shanghai")


if __name__ == "__main__":
    unittest.main()
