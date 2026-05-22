import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_DATA_SOURCE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "sunset" / "data_source.py"
_SPEC = spec_from_file_location("sunset_data_source", _DATA_SOURCE_PATH)
assert _SPEC is not None
sunset_data_source = module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(sunset_data_source)


class SunsetDataSourceTestCase(unittest.TestCase):
    def test_split_metric_extracts_score_and_level(self) -> None:
        self.assertEqual(sunset_data_source._split_metric("0.058（小烧）"), ("0.058", "小烧"))

    def test_format_date_uses_chinese_month_day(self) -> None:
        self.assertEqual(sunset_data_source._format_date("2026-05-23 19:27:34"), "5月23日")

    def test_format_event_line_includes_quality_and_aod(self) -> None:
        line = sunset_data_source._format_event_line(
            "set_1",
            {
                "status": "ok",
                "tb_event_time": "2026-05-23 19:27:34",
                "tb_quality": "0.058（小烧）",
                "tb_aod": "0.743（大污）",
            },
        )

        self.assertEqual(line, "日落时分（2026-05-23 19:27:34）：0.058（小烧），AOD 0.743（大污）")

    def test_build_sunset_alert_ignores_small_burn(self) -> None:
        alert = sunset_data_source.build_sunset_alert(
            [
                (
                    "set_1",
                    {
                        "status": "ok",
                        "place_holder": "北京",
                        "display_model": "GFS",
                        "tb_event_time": "2026-05-23 19:27:34",
                        "tb_quality": "0.058（小烧）",
                        "tb_aod": "0.743（大污）",
                    },
                )
            ]
        )

        self.assertEqual(alert, "")

    def test_build_sunset_alert_reports_medium_burn(self) -> None:
        alert = sunset_data_source.build_sunset_alert(
            [
                (
                    "set_2",
                    {
                        "status": "ok",
                        "place_holder": "北京",
                        "display_model": "GFS",
                        "tb_event_time": "2026-05-24 19:28:25",
                        "tb_quality": "0.210（中烧）",
                        "tb_aod": "0.499（小污）",
                    },
                )
            ]
        )

        self.assertIn("火烧云提醒：北京（GFS） 今日/明日可能达到中烧或以上。", alert)
        self.assertIn("明日日落时分（2026-05-24 19:28:25）：0.210（中烧），AOD 0.499（小污）", alert)


if __name__ == "__main__":
    unittest.main()
