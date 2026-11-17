"""Offline contracts; fixture is a reduced real Glow response from 2026-11-17."""

import copy
import importlib.util
import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sky_sources", ROOT / "src/plugins/sunset/sources.py"
)
sky = importlib.util.module_from_spec(spec)
if spec.loader:
    spec.loader.exec_module(sky)
TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 11, 17, 10, 40, tzinfo=TZ)


class GlowTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(
            (ROOT / "tests/fixtures/sky/glow_beijing.json").read_text()
        )

    def test_real_shape_separates_quality_and_probability(self):
        result = sky.normalize_glow(self.raw, "2026-11-17", "beijing", NOW)
        self.assertEqual(result["quality"], 54)
        self.assertEqual(result["probability"], 49)
        self.assertIsNone(result["score"])
        self.assertEqual(result["event_time"], "2026-11-17T16:56:00+08:00")
        self.assertEqual(result["status"], "valid")
        self.assertEqual(
            result["cloud_evidence"]["mid"],
            self.raw["prediction"]["metrics"]["cloudMid"],
        )

    def test_missing_null_expired_and_transition_state(self):
        for field, expired in [
            ("quality", "qualityValidUntil"),
            ("probability", "probabilityValidUntil"),
        ]:
            raw = copy.deepcopy(self.raw)
            raw["prediction"][field] = None
            self.assertIsNone(
                sky.normalize_glow(raw, "2026-11-17", "beijing", NOW)[field]
            )
            raw = copy.deepcopy(self.raw)
            raw["prediction"][expired] = "2026-11-17T01:00:00Z"
            self.assertIsNone(
                sky.normalize_glow(raw, "2026-11-17", "beijing", NOW)[field]
            )
        raw = copy.deepcopy(self.raw)
        raw["prediction"]["cloudglowTransitions"] = [
            dict(effectiveAt="2026-11-17T02:30:00Z", quality=61),
            dict(effectiveAt="2026-11-17T03:00:00Z", quality=99),
        ]
        self.assertEqual(
            sky.normalize_glow(raw, "2026-11-17", "beijing", NOW)["quality"], 61
        )
        raw["prediction"]["freshness"]["quality"] = "expired"
        self.assertIsNone(
            sky.normalize_glow(raw, "2026-11-17", "beijing", NOW)["quality"]
        )

    def test_identity_and_acquisition_mismatches(self):
        for key, value in [
            ("spot", "shanghai"),
            ("date", "2026-11-18"),
            ("businessDate", "2026-11-18"),
            ("fetchedAt", None),
            ("fetchedAt", "2026-11-17T05:00:00Z"),
        ]:
            raw = copy.deepcopy(self.raw)
            raw["prediction"][key] = value
            with self.assertRaises(ValueError):
                sky.normalize_glow(raw, "2026-11-17", "beijing", NOW)
        self.assertEqual(
            sky.normalize_glow(self.raw, "2026-11-17", "beijing", NOW.replace(hour=18))[
                "status"
            ],
            "passed",
        )
        result = sky.normalize_glow(
            self.raw, "2026-11-17", "beijing", NOW.replace(hour=13)
        )
        self.assertIsNone(result["quality"])
        self.assertIsNone(result["probability"])
        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["cloud_evidence"]["mid"])
        raw = copy.deepcopy(self.raw)
        raw["prediction"]["cloudglowTransitions"] = []
        result = sky.normalize_glow(raw, "2026-11-17", "beijing", NOW.replace(hour=13))
        self.assertIsNone(result["cloud_evidence"]["mid"])


class CityTests(unittest.TestCase):
    def test_resolves_actual_summary_and_never_falls_back(self):
        summary = json.loads(
            (ROOT / "tests/fixtures/sky/glow_summary.json").read_text()
        )
        self.assertEqual(
            sky.resolve_glow_spot(summary, "北京市", "2026-11-17"), "beijing"
        )
        self.assertIsNone(sky.resolve_glow_spot(summary, "不存在市", "2026-11-17"))
        self.assertIsNone(sky.resolve_glow_spot(summary, "北京", "2026-11-18"))

    def test_geocode_selects_unique_administrative_city_over_homonymous_village(self):
        city = {
            "name": "北京",
            "country_code": "CN",
            "latitude": 39.9075,
            "longitude": 116.39723,
            "feature_code": "PPLC",
        }
        village = dict(city, latitude=30.72608, longitude=108.67483, feature_code="PPL")
        self.assertEqual(
            sky.resolve_geocode({"results": [city, village]}, "北京")["lat"], 39.9075
        )
        with self.assertRaises(ValueError):
            sky.resolve_geocode({"results": [city, dict(city, latitude=30)]}, "北京")

    def test_geocode_rejects_wrong_or_ambiguous_city(self):
        city = {
            "name": "北京",
            "country_code": "CN",
            "latitude": 39.9075,
            "longitude": 116.3972,
        }
        self.assertEqual(
            sky.resolve_geocode({"results": [city]}, "北京市")["lat"], 39.9075
        )
        for requested, results in [
            ("上海", [city]),
            ("北京", []),
            ("北京", [city, dict(city, latitude=40.8)]),
        ]:
            with self.assertRaises(ValueError):
                sky.resolve_geocode({"results": results}, requested)


class LocalTests(unittest.TestCase):
    def inputs(self):
        from datetime import timedelta

        times = [
            (NOW.replace(hour=0, minute=0) + timedelta(hours=i)).strftime(
                "%Y-%m-%dT%H:%M"
            )
            for i in range(72)
        ]
        hourly = {"time": times}
        fields = dict(
            cloud_cover=60,
            cloud_cover_low=10,
            cloud_cover_mid=50,
            cloud_cover_high=30,
            relative_humidity_2m=65,
            visibility=25000,
            wind_speed_10m=8,
            wind_direction_10m=90,
            precipitation=0,
            precipitation_probability=0,
            weather_code=2,
        )
        hourly.update({k: [v] * 72 for k, v in fields.items()})
        daily = {
            "time": ["2026-11-17", "2026-11-18", "2026-11-19"],
            "sunrise": [f"2026-11-{d}T07:00" for d in (17, 18, 19)],
            "sunset": [f"2026-11-{d}T17:00" for d in (17, 18, 19)],
        }
        return {
            "latitude": 39.9,
            "longitude": 116.4,
            "timezone": "Asia/Shanghai",
            "hourly": hourly,
            "daily": daily,
        }, {"hourly": {"time": times, "pm2_5": [20] * 72}}

    def test_pinned_engine_and_missing_fields_fail_closed(self):
        fc, air = self.inputs()
        city = dict(id="beijing", name="北京", lat=39.9, lon=116.4, region="北京")
        data = sky.compute_local(city, fc, air, NOW)
        results = sky.normalize_local(data, fc, air, city, NOW, NOW)
        self.assertEqual(len(results), 4)
        self.assertGreater(results[1]["score"], 70)
        self.assertEqual(results[0]["status"], "passed")
        fc["hourly"]["cloud_cover_mid"] = [None] * 72
        results = sky.normalize_local(data, fc, air, city, NOW, NOW)
        self.assertIsNone(results[1]["score"])
        self.assertEqual(results[1]["status"], "unknown")

    def test_window_requires_every_hour(self):
        event = NOW.replace(hour=17, minute=30)
        hourly = {
            "time": ["2026-11-17T16:00", "2026-11-17T18:00"],
            "precipitation": [0, 0],
        }
        self.assertFalse(sky.complete_window(hourly, event, -90, 45, ["precipitation"]))

    def test_wrong_city_date_and_old_collection_are_rejected(self):
        from datetime import timedelta

        fc, air = self.inputs()
        city = dict(id="beijing", name="北京", lat=39.9, lon=116.4, region="北京")
        data = sky.compute_local(city, fc, air, NOW)
        for bad in [
            dict(data, id="shanghai"),
            dict(data, today=dict(data["today"], date="2026-11-16")),
        ]:
            with self.assertRaises(ValueError):
                sky.normalize_local(bad, fc, air, city, NOW, NOW)
        stale = sky.normalize_local(data, fc, air, city, NOW, NOW - timedelta(hours=1))[
            1
        ]
        self.assertIsNone(stale["score"])
        self.assertIsNone(stale["cloud_evidence"]["mid"])
        self.assertIsNone(stale["weather"]["precipitation"])


class CollectionTests(unittest.TestCase):
    def test_request_timeout_is_clamped_and_body_is_bounded(self):
        from unittest.mock import MagicMock, patch

        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with patch.object(sky, "urlopen", return_value=response) as request:
            self.assertEqual(sky.get_json("https://example.invalid", {}, 90), {})
        self.assertEqual(request.call_args.kwargs["timeout"], 5)
        response.__enter__.return_value.read.assert_called_once_with(2_000_001)

    def test_glow_429_stops_source(self):
        from unittest.mock import patch
        from urllib.error import HTTPError

        with patch.object(
            sky,
            "get_json",
            side_effect=HTTPError("https://glowsunset.cn", 429, "rate limit", {}, None),
        ) as request:
            data = sky.collect_glow("北京", NOW, 5)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(data["errors"][0], "http_429")
        self.assertEqual(data["entries"], [])

    def test_glow_queries_resolved_city_and_version(self):
        from unittest.mock import patch

        summary = json.loads(
            (ROOT / "tests/fixtures/sky/glow_summary.json").read_text()
        )
        raw = json.loads((ROOT / "tests/fixtures/sky/glow_beijing.json").read_text())
        with patch.object(
            sky, "get_json", side_effect=[summary, raw, summary]
        ) as request:
            data = sky.collect_glow("北京市", NOW, 5)
        self.assertEqual(data["entries"][0]["spot"], "beijing")
        self.assertEqual(
            request.call_args_list[1].args[1]["version"], summary["version"]
        )
        self.assertTrue(data["errors"])  # tomorrow absent: unknown, not today's reuse


if __name__ == "__main__":
    unittest.main()
