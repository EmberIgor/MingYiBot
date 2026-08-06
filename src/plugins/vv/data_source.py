from __future__ import annotations

import asyncio
import json
import re
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nonebot import logger


SEARCH_RESULT_LIMIT = 5
MAX_SEARCH_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_FRAME_BYTES = 5 * 1024 * 1024
EPISODE_PATTERN = re.compile(r"\[P(\d+)\]")
TIMESTAMP_PATTERN = re.compile(r"^(\d+)m(\d+)s$")


class VVError(RuntimeError):
    pass


class VVTimeoutError(VVError):
    pass


class VVResponseError(VVError):
    pass


class VVNoResultError(VVError):
    pass


class VVImageError(VVError):
    pass


@dataclass(frozen=True)
class VVResult:
    episode_id: int
    frame_number: int


class VVClient:
    def __init__(
        self,
        *,
        api_url: str,
        image_base_url: str,
        timeout_seconds: float,
        index_cache_seconds: float,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.image_base_url = image_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.index_cache_seconds = index_cache_seconds
        self._index_cache: dict[int, tuple[float, bytes]] = {}
        self._cache_lock = threading.Lock()

    async def fetch_best_image(self, query: str) -> bytes:
        return await asyncio.to_thread(self._fetch_best_image, query)

    def _fetch_best_image(self, query: str) -> bytes:
        payload = self._search(query)
        candidates = parse_search_response(payload)
        parsed_candidates = [result for item in candidates if (result := parse_result(item)) is not None]
        if not parsed_candidates:
            raise VVNoResultError("没有找到匹配的 VV 表情包。")

        for result in parsed_candidates:
            try:
                image = self._fetch_frame(result.episode_id, result.frame_number)
                logger.info("VV frame fetched: episode=P{}, frame={}", result.episode_id, result.frame_number)
                return image
            except VVImageError as exc:
                logger.warning(
                    "VV candidate image failed: episode=P{}, frame={}, error={}",
                    result.episode_id,
                    result.frame_number,
                    type(exc).__name__,
                )
                continue
        raise VVImageError("匹配到了台词，但暂时无法取得对应图片。")

    def _search(self, query: str) -> bytes:
        url = f"{self.api_url}/search?{urlencode({'query': query, 'max_results': SEARCH_RESULT_LIMIT})}"
        request = Request(
            url,
            headers={"User-Agent": "MingYiBot/1.0", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return _read_limited(response, MAX_SEARCH_RESPONSE_BYTES, VVResponseError)
        except (TimeoutError, socket.timeout) as exc:
            raise VVTimeoutError("VV 搜索服务响应超时。") from exc
        except HTTPError as exc:
            raise VVResponseError(f"VV 搜索服务返回 HTTP {exc.code}。") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise VVTimeoutError("VV 搜索服务响应超时。") from exc
            raise VVResponseError("无法连接 VV 搜索服务。") from exc
        except OSError as exc:
            raise VVResponseError("无法连接 VV 搜索服务。") from exc

    def _fetch_frame(self, episode_id: int, frame_number: int) -> bytes:
        group_index = (episode_id - 1) // 10
        index_data = self._get_index(group_index)
        offsets = parse_index(index_data, episode_id, frame_number)
        if offsets is None:
            raise VVImageError("索引中没有对应图片。")

        start_offset, end_offset = offsets
        range_value = f"bytes={start_offset}-{end_offset - 1}" if end_offset is not None else f"bytes={start_offset}-"
        request = Request(
            f"{self.image_base_url}/{group_index}.webp",
            headers={
                "User-Agent": "MingYiBot/1.0",
                "Accept": "image/webp",
                "Range": range_value,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", response.getcode())
                if status != 206:
                    raise VVImageError("图片服务未返回字节范围响应。")
                content_type = response.headers.get_content_type().lower()
                if content_type != "image/webp":
                    raise VVImageError("图片服务返回了非 WebP 内容。")
                content_range = str(response.headers.get("Content-Range") or "")
                if not content_range.startswith(f"bytes {start_offset}-"):
                    raise VVImageError("图片服务返回的字节范围不正确。")
                data = _read_limited(response, MAX_FRAME_BYTES, VVImageError)
        except VVImageError:
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise VVImageError("获取 VV 图片超时。") from exc
        except (HTTPError, URLError, OSError) as exc:
            raise VVImageError("获取 VV 图片失败。") from exc

        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise VVImageError("图片数据不是有效的 WebP。")
        return data

    def _get_index(self, group_index: int) -> bytes:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._index_cache.get(group_index)
            if cached is not None and now - cached[0] < self.index_cache_seconds:
                return cached[1]

        request = Request(
            f"{self.image_base_url}/{group_index}.index",
            headers={"User-Agent": "MingYiBot/1.0", "Accept": "application/octet-stream"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = _read_limited(response, MAX_INDEX_BYTES, VVImageError)
        except VVImageError:
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise VVImageError("获取 VV 图片索引超时。") from exc
        except (HTTPError, URLError, OSError) as exc:
            raise VVImageError("获取 VV 图片索引失败。") from exc

        with self._cache_lock:
            self._index_cache[group_index] = (now, data)
        return data


def parse_search_response(payload: bytes | str) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    except UnicodeDecodeError as exc:
        raise VVResponseError("VV 搜索服务返回了无法识别的文本。") from exc
    text = text.strip()
    if not text:
        return []

    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None

    if decoded is not None:
        return _normalize_search_payload(decoded)

    results: list[dict[str, Any]] = []
    valid_json_lines = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        valid_json_lines += 1
        if isinstance(item, dict) and _is_error_payload(item):
            raise VVResponseError(str(item.get("message") or item.get("error") or "VV 搜索失败。"))
        if isinstance(item, dict):
            results.append(item)
    if not valid_json_lines:
        raise VVResponseError("VV 搜索服务返回格式异常。")
    return results


def _normalize_search_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if _is_error_payload(payload):
            raise VVResponseError(str(payload.get("message") or payload.get("error") or "VV 搜索失败。"))
        if isinstance(payload.get("results"), list):
            return [item for item in payload["results"] if isinstance(item, dict)]
        if "filename" in payload:
            return [payload]
    raise VVResponseError("VV 搜索服务返回格式异常。")


def _is_error_payload(payload: dict[str, Any]) -> bool:
    return payload.get("status") == "error" or ("error" in payload and "filename" not in payload)


def parse_result(item: dict[str, Any]) -> VVResult | None:
    filename = str(item.get("filename") or "")
    timestamp = str(item.get("timestamp") or "")
    episode_match = EPISODE_PATTERN.search(filename)
    time_match = TIMESTAMP_PATTERN.fullmatch(timestamp)
    if episode_match is None or time_match is None:
        return None
    episode_id = int(episode_match.group(1))
    minutes = int(time_match.group(1))
    seconds = int(time_match.group(2))
    if episode_id <= 0 or seconds >= 60:
        return None
    return VVResult(episode_id=episode_id, frame_number=minutes * 60 + seconds)


def parse_index(index_data: bytes, episode_id: int, frame_number: int) -> tuple[int, int | None] | None:
    if len(index_data) < 16:
        raise VVImageError("VV 图片索引已损坏。")
    try:
        _, _, folder_count = struct.unpack_from("<III", index_data, 0)
    except struct.error as exc:
        raise VVImageError("VV 图片索引已损坏。") from exc

    file_count_offset = 12 + folder_count * 4
    if file_count_offset + 4 > len(index_data):
        raise VVImageError("VV 图片索引已损坏。")
    file_count = struct.unpack_from("<I", index_data, file_count_offset)[0]
    records_offset = file_count_offset + 4
    records_end = records_offset + file_count * 16
    if file_count == 0 or records_end > len(index_data):
        raise VVImageError("VV 图片索引已损坏。")

    left, right = 0, file_count - 1
    while left <= right:
        middle = (left + right) // 2
        record_offset = records_offset + middle * 16
        current_episode, current_frame, start_offset = struct.unpack_from("<IIQ", index_data, record_offset)
        current_key = (current_episode, current_frame)
        target_key = (episode_id, frame_number)
        if current_key == target_key:
            end_offset = None
            if middle + 1 < file_count:
                end_offset = struct.unpack_from("<Q", index_data, record_offset + 24)[0]
                if end_offset <= start_offset:
                    raise VVImageError("VV 图片索引包含无效范围。")
            return start_offset, end_offset
        if current_key < target_key:
            left = middle + 1
        else:
            right = middle - 1
    return None


def _read_limited(response: Any, limit: int, error_type: type[VVError]) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise error_type("上游响应体积过大。")
        except ValueError:
            pass
    data = response.read(limit + 1)
    if len(data) > limit:
        raise error_type("上游响应体积过大。")
    return data
