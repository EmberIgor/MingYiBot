from __future__ import annotations

import asyncio
import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import SearchError, SearchResponse, SearchResult

EXA_SEARCH_URL = "https://api.exa.ai/search"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUERY_CHARACTERS = 500
MAX_TITLE_CHARACTERS = 300
MAX_AUTHOR_CHARACTERS = 200


class ExaSearchProvider:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 15.0,
        num_results: int = 5,
        highlight_max_characters: int = 1200,
    ) -> None:
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.num_results = num_results
        self.highlight_max_characters = highlight_max_characters

    async def search(self, query: str) -> SearchResponse:
        return await asyncio.to_thread(self._search, query)

    def _search(self, query: str) -> SearchResponse:
        query = " ".join(str(query).split()).strip()
        if not query:
            raise SearchError("invalid_query", "搜索关键词不能为空。")
        if not self.api_key:
            raise SearchError("not_configured", "Exa API Key 尚未配置。")
        query = query[:MAX_QUERY_CHARACTERS]

        body = json.dumps(
            {
                "query": query,
                "type": "auto",
                "numResults": self.num_results,
                "contents": {"highlights": {"maxCharacters": self.highlight_max_characters}},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            EXA_SEARCH_URL,
            data=body,
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "MingYiBot/1.0",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = _read_limited(response)
        except (TimeoutError, socket.timeout) as exc:
            raise SearchError("timeout", "Exa 搜索响应超时。") from exc
        except HTTPError as exc:
            raise _http_error(exc) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise SearchError("timeout", "Exa 搜索响应超时。") from exc
            raise SearchError("connection_error", "暂时无法连接 Exa 搜索服务。") from exc
        except OSError as exc:
            raise SearchError("connection_error", "暂时无法连接 Exa 搜索服务。") from exc

        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SearchError("invalid_response", "Exa 搜索返回了无效数据。") from exc
        if not isinstance(decoded, dict) or not isinstance(decoded.get("results"), list):
            raise SearchError("invalid_response", "Exa 搜索返回的数据格式异常。")

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for item in decoded["results"]:
            result = _normalize_result(item, self.highlight_max_characters)
            if result is None or result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            results.append(result)
            if len(results) >= self.num_results:
                break
        return SearchResponse(query=query, results=tuple(results))


def _read_limited(response: Any) -> bytes:
    payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise SearchError("response_too_large", "Exa 搜索返回的数据过大。")
    return payload


def _http_error(exc: HTTPError) -> SearchError:
    messages = {
        401: ("authentication_failed", "Exa API Key 无效。"),
        402: ("credits_exhausted", "Exa 搜索额度已用尽或预算已达上限。"),
        403: ("forbidden", "Exa 搜索请求没有访问权限。"),
        429: ("rate_limited", "Exa 搜索请求过于频繁，请稍后再试。"),
    }
    code, message = messages.get(
        exc.code,
        ("server_error" if exc.code >= 500 else "request_failed", f"Exa 搜索请求失败（HTTP {exc.code}）。"),
    )
    return SearchError(code, message, status_code=exc.code)


def _normalize_result(item: Any, highlight_limit: int) -> SearchResult | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or item.get("id") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    title = _compact(item.get("title"), MAX_TITLE_CHARACTERS) or parsed.netloc
    highlights_value = item.get("highlights")
    if isinstance(highlights_value, str):
        highlights_value = [highlights_value]
    highlights: list[str] = []
    remaining = max(highlight_limit, 1)
    if isinstance(highlights_value, list):
        for value in highlights_value:
            text = _compact(value, remaining)
            if not text:
                continue
            highlights.append(text)
            remaining -= len(text)
            if remaining <= 0:
                break
    return SearchResult(
        title=title,
        url=url,
        published_date=_compact(item.get("publishedDate"), 64),
        author=_compact(item.get("author"), MAX_AUTHOR_CHARACTERS),
        highlights=tuple(highlights),
    )


def _compact(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[: max(limit, 0)]
