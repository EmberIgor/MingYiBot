from __future__ import annotations

import asyncio
import socket
import struct
import unittest
from email.message import Message as HeaderMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent
from pydantic import ValidationError

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

import src.plugins.vv as vv
from src.plugins.vv.config import Config
from src.plugins.vv.data_source import (
    MAX_FRAME_BYTES,
    VVClient,
    VVImageError,
    VVNoResultError,
    VVResponseError,
    VVTimeoutError,
    parse_index,
    parse_result,
    parse_search_response,
)


class VVConfigTest(unittest.TestCase):
    def test_defaults_allow_old_environment_without_vv_settings(self) -> None:
        config = Config()

        self.assertEqual(config.vv_api_url, "https://vvapi.cicada000.work")
        self.assertEqual(config.vv_image_base_url, "https://vv.noxylva.org")
        self.assertEqual(config.vv_timeout_seconds, 10.0)
        self.assertEqual(config.vv_cooldown_seconds, 10.0)
        self.assertEqual(config.vv_index_cache_seconds, 3600.0)

    def test_partial_override_preserves_other_defaults(self) -> None:
        config = Config(vv_timeout_seconds=4.5)

        self.assertEqual(config.vv_timeout_seconds, 4.5)
        self.assertEqual(config.vv_cooldown_seconds, 10.0)

    def test_non_positive_timing_values_are_rejected(self) -> None:
        for field in ("vv_timeout_seconds", "vv_cooldown_seconds", "vv_index_cache_seconds"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Config(**{field: 0})


class VVSearchParsingTest(unittest.TestCase):
    def test_parses_json_lines_and_skips_malformed_lines(self) -> None:
        payload = '\n'.join(
            [
                '{"filename":"[P086] demo.json","timestamp":"4m23s"}',
                'not-json',
                '{"filename":"[P001] demo.json","timestamp":"0m05s"}',
            ]
        )

        results = parse_search_response(payload)

        self.assertEqual(len(results), 2)

    def test_parses_json_array(self) -> None:
        results = parse_search_response('[{"filename":"[P001] demo.json","timestamp":"0m05s"}]')

        self.assertEqual(results[0]["timestamp"], "0m05s")

    def test_rejects_error_payload_and_fully_malformed_response(self) -> None:
        with self.assertRaises(VVResponseError):
            parse_search_response('{"status":"error","message":"failed"}')
        with self.assertRaises(VVResponseError):
            parse_search_response("not-json")

    def test_result_parsing_converts_timestamp_and_rejects_invalid_values(self) -> None:
        result = parse_result({"filename": "[P086] demo.json", "timestamp": "4m23s"})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual((result.episode_id, result.frame_number), (86, 263))
        self.assertIsNone(parse_result({"filename": "demo.json", "timestamp": "4m23s"}))
        self.assertIsNone(parse_result({"filename": "[P086] demo.json", "timestamp": "4m60s"}))


class VVIndexTest(unittest.TestCase):
    def test_parses_first_middle_and_last_records(self) -> None:
        data = _build_index([(1, 5, 100), (1, 6, 116), (2, 1, 140)])

        self.assertEqual(parse_index(data, 1, 5), (100, 116))
        self.assertEqual(parse_index(data, 1, 6), (116, 140))
        self.assertEqual(parse_index(data, 2, 1), (140, None))
        self.assertIsNone(parse_index(data, 1, 7))

    def test_rejects_truncated_and_invalid_ranges(self) -> None:
        with self.assertRaises(VVImageError):
            parse_index(b"short", 1, 1)
        with self.assertRaises(VVImageError):
            parse_index(_build_index([(1, 5, 100), (1, 6, 90)]), 1, 5)


class VVNetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = VVClient(
            api_url="https://api.example",
            image_base_url="https://images.example",
            timeout_seconds=10,
            index_cache_seconds=3600,
        )

    def test_fetch_frame_uses_range_and_accepts_valid_webp(self) -> None:
        index_response = FakeResponse(_build_index([(1, 5, 100), (1, 6, 116)]))
        image_data = b"RIFF\x08\x00\x00\x00WEBPdata"
        image_response = FakeResponse(
            image_data,
            status=206,
            content_type="image/webp",
            extra_headers={"Content-Range": "bytes 100-115/1000"},
        )

        with patch("src.plugins.vv.data_source.urlopen", side_effect=[index_response, image_response]) as mocked:
            result = self.client._fetch_frame(1, 5)

        self.assertEqual(result, image_data)
        request = mocked.call_args_list[1].args[0]
        self.assertEqual(request.get_header("Range"), "bytes=100-115")

    def test_fetch_frame_rejects_ignored_range_wrong_type_and_oversized_body(self) -> None:
        cases = [
            FakeResponse(b"RIFF\x08\x00\x00\x00WEBPdata", status=200, content_type="image/webp"),
            FakeResponse(
                b"not-an-image",
                status=206,
                content_type="text/html",
                extra_headers={"Content-Range": "bytes 100-115/1000"},
            ),
            FakeResponse(
                b"x" * (MAX_FRAME_BYTES + 1),
                status=206,
                content_type="image/webp",
                extra_headers={"Content-Range": "bytes 100-115/1000"},
            ),
        ]
        for image_response in cases:
            with self.subTest(status=image_response.status, content_type=image_response.headers.get_content_type()):
                self.client._index_cache.clear()
                with (
                    patch(
                        "src.plugins.vv.data_source.urlopen",
                        side_effect=[FakeResponse(_build_index([(1, 5, 100), (1, 6, 116)])), image_response],
                    ),
                    self.assertRaises(VVImageError),
                ):
                    self.client._fetch_frame(1, 5)

    def test_search_maps_timeout_and_http_failure(self) -> None:
        with patch("src.plugins.vv.data_source.urlopen", side_effect=socket.timeout()), self.assertRaises(VVTimeoutError):
            self.client._search("测试")
        with (
            patch(
                "src.plugins.vv.data_source.urlopen",
                side_effect=HTTPError("https://api.example/search", 503, "unavailable", {}, None),
            ),
            self.assertRaises(VVResponseError),
        ):
            self.client._search("测试")

    def test_best_image_skips_invalid_metadata_and_unavailable_candidate(self) -> None:
        payload = (
            '[{"filename":"bad","timestamp":"bad"},'
            '{"filename":"[P001] one.json","timestamp":"0m05s"},'
            '{"filename":"[P002] two.json","timestamp":"0m06s"}]'
        ).encode()
        with (
            patch.object(self.client, "_search", return_value=payload),
            patch.object(self.client, "_fetch_frame", side_effect=[VVImageError("missing"), b"image"]) as fetch,
        ):
            result = self.client._fetch_best_image("测试")

        self.assertEqual(result, b"image")
        self.assertEqual(fetch.call_count, 2)

    def test_best_image_reports_no_result(self) -> None:
        with patch.object(self.client, "_search", return_value=b"[]"), self.assertRaises(VVNoResultError):
            self.client._fetch_best_image("missing")


class VVCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        vv.cooldowns.clear()

    def test_empty_query_returns_usage_without_starting_cooldown(self) -> None:
        event = _group_event(100, ".vv")

        response = asyncio.run(vv._build_response(event))

        self.assertEqual(response, "用法：.vv 关键词")
        self.assertEqual(vv.cooldowns, {})

    def test_success_returns_one_base64_image(self) -> None:
        event = _group_event(100, "。vv 测试")
        original_client = vv.client
        vv.client = SimpleNamespace(fetch_best_image=AsyncMock(return_value=b"image-data"))
        try:
            response = asyncio.run(vv._build_response(event))
        finally:
            vv.client = original_client

        self.assertEqual(response.type, "image")
        self.assertTrue(str(response.data["file"]).startswith("base64://"))

    def test_cooldown_isolated_by_group_and_private_user(self) -> None:
        self.assertEqual(vv._take_cooldown(("group", 100), now=100.0), 0)
        self.assertEqual(vv._take_cooldown(("group", 100), now=101.0), 9)
        self.assertEqual(vv._take_cooldown(("group", 200), now=101.0), 0)
        self.assertEqual(vv._take_cooldown(("private", 100), now=101.0), 0)

    def test_command_maps_expected_failures_to_user_messages(self) -> None:
        cases = [
            (VVTimeoutError("timeout"), "VV 搜索服务响应超时"),
            (VVNoResultError("missing"), "没有找到匹配"),
            (VVImageError("image"), "无法取得对应图片"),
            (VVResponseError("bad"), "搜索服务暂时不可用"),
        ]
        original_client = vv.client
        try:
            for index, (error, expected) in enumerate(cases, 1):
                with self.subTest(error=type(error).__name__):
                    vv.cooldowns.clear()
                    vv.client = SimpleNamespace(fetch_best_image=AsyncMock(side_effect=error))
                    response = asyncio.run(vv._build_response(_private_event(index, ".vv 测试")))
                    self.assertIn(expected, response)
        finally:
            vv.client = original_client


class FakeResponse:
    def __init__(
        self,
        data: bytes,
        *,
        status: int = 200,
        content_type: str = "application/octet-stream",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.data = data
        self.status = status
        self.headers = HeaderMessage()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(data))
        for key, value in (extra_headers or {}).items():
            self.headers[key] = value

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, amount: int = -1) -> bytes:
        return self.data if amount < 0 else self.data[:amount]


def _build_index(records: list[tuple[int, int, int]]) -> bytes:
    return b"".join(
        [
            struct.pack("<III", 0, 0, 0),
            struct.pack("<I", len(records)),
            *(struct.pack("<IIQ", *record) for record in records),
        ]
    )


def _group_event(group_id: int, message: str) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=1,
        message=Message(message),
        original_message=Message(message),
        raw_message=message,
        font=0,
        sender={"user_id": 123, "nickname": "test", "card": "", "role": "member"},
        to_me=False,
        reply=None,
        group_id=group_id,
        anonymous=None,
    )


def _private_event(user_id: int, message: str) -> PrivateMessageEvent:
    return PrivateMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="friend",
        user_id=user_id,
        message_type="private",
        message_id=1,
        message=Message(message),
        original_message=Message(message),
        raw_message=message,
        font=0,
        sender={"user_id": user_id, "nickname": "test"},
        to_me=False,
        reply=None,
        target_id=1,
        temp_source=0,
    )


if __name__ == "__main__":
    unittest.main()
