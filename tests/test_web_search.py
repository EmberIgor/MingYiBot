from __future__ import annotations

import asyncio
import io
import json
import socket
import unittest
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError

import nonebot
from pydantic import ValidationError

nonebot.init()

from src.common.ai.responses import SearchToolUnsupportedError, request_response_with_search
from src.common.search import ExaSearchProvider, SearchError, SearchResponse, SearchResult
from src.plugins.ai_chat.config import Config


class FakeHTTPResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.payload if limit < 0 else self.payload[:limit]


class FakeResponse:
    def __init__(self, output: list[dict[str, Any]], output_text: str = "") -> None:
        self.output = output
        self.output_text = output_text


class FakeResponsesClient:
    def __init__(self, responses: list[Any]) -> None:
        self.queued = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        item = self.queued.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = FakeResponsesClient(responses)


class RecordingProvider:
    def __init__(self, error: SearchError | None = None) -> None:
        self.queries: list[str] = []
        self.error = error

    async def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        if self.error:
            raise self.error
        return SearchResponse(
            query=query,
            results=(SearchResult("Example", "https://example.com", highlights=("fact",)),),
        )


def tool_call(call_id: str, query: str = "latest news") -> FakeResponse:
    return FakeResponse(
        [{"type": "function_call", "name": "web_search", "call_id": call_id, "arguments": json.dumps({"query": query})}]
    )


class ExaSearchProviderTest(unittest.TestCase):
    def test_config_defaults_and_bounds(self) -> None:
        config = Config()
        self.assertEqual(config.exa_timeout_seconds, 15.0)
        self.assertEqual(config.exa_num_results, 5)
        self.assertEqual(config.exa_highlight_max_characters, 1200)
        with self.assertRaises(ValidationError):
            Config(exa_num_results=0)
        with self.assertRaises(ValidationError):
            Config(exa_num_results=11)

    def test_request_and_response_normalization(self) -> None:
        payload = json.dumps(
            {
                "results": [
                    {
                        "title": " Demo  title ",
                        "url": "https://example.com/a",
                        "publishedDate": "2026-08-22",
                        "author": " Author ",
                        "highlights": [" useful   fact "],
                    },
                    {"title": "duplicate", "url": "https://example.com/a"},
                    {"title": "unsafe", "url": "file:///etc/passwd"},
                ]
            }
        ).encode()
        provider = ExaSearchProvider("secret", num_results=5, highlight_max_characters=100)

        def fake_urlopen(request: Any, timeout: float) -> FakeHTTPResponse:
            self.assertEqual(timeout, 15.0)
            self.assertEqual(request.get_header("X-api-key"), "secret")
            body = json.loads(request.data)
            self.assertEqual(body["type"], "auto")
            self.assertEqual(body["numResults"], 5)
            self.assertEqual(body["contents"]["highlights"]["maxCharacters"], 100)
            return FakeHTTPResponse(payload)

        with patch("src.common.search.exa.urlopen", side_effect=fake_urlopen):
            result = asyncio.run(provider.search("  demo   query  "))

        self.assertEqual(result.query, "demo query")
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].title, "Demo title")
        self.assertEqual(result.results[0].highlights, ("useful fact",))

    def test_error_mapping_and_invalid_payload(self) -> None:
        provider = ExaSearchProvider("secret")
        cases = [
            (socket.timeout(), "timeout"),
            (HTTPError("url", 401, "bad", {}, io.BytesIO()), "authentication_failed"),
            (HTTPError("url", 402, "bad", {}, io.BytesIO()), "credits_exhausted"),
            (HTTPError("url", 429, "bad", {}, io.BytesIO()), "rate_limited"),
            (HTTPError("url", 503, "bad", {}, io.BytesIO()), "server_error"),
        ]
        for error, expected_code in cases:
            with self.subTest(expected_code), patch("src.common.search.exa.urlopen", side_effect=error):
                with self.assertRaises(SearchError) as raised:
                    asyncio.run(provider.search("query"))
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("secret", str(raised.exception))

        with patch("src.common.search.exa.urlopen", return_value=FakeHTTPResponse(b"not-json")):
            with self.assertRaises(SearchError) as raised:
                asyncio.run(provider.search("query"))
            self.assertEqual(raised.exception.code, "invalid_response")


class ResponsesSearchLoopTest(unittest.TestCase):
    def run_search(self, responses: list[Any], provider: RecordingProvider | None = None):
        client = FakeClient(responses)
        provider = provider or RecordingProvider()
        result = asyncio.run(
            request_response_with_search(
                client,
                "model",
                "instructions",
                [{"role": "user", "content": "hello"}],
                provider,
            )
        )
        return result, client, provider

    def test_model_can_answer_without_search(self) -> None:
        result, client, provider = self.run_search([FakeResponse([], "plain answer")])
        self.assertEqual(result.response.output_text, "plain answer")
        self.assertEqual(provider.queries, [])
        self.assertEqual(client.responses.requests[0]["tool_choice"], "auto")
        self.assertFalse(client.responses.requests[0]["parallel_tool_calls"])

    def test_one_search_returns_sources_and_tool_output(self) -> None:
        result, client, provider = self.run_search([tool_call("call-1"), FakeResponse([], "answer")])
        self.assertEqual(provider.queries, ["latest news"])
        self.assertEqual([item.url for item in result.sources], ["https://example.com"])
        tool_output = client.responses.requests[1]["input"][-1]
        self.assertEqual(tool_output["type"], "function_call_output")
        self.assertTrue(json.loads(tool_output["output"])["ok"])

    def test_third_search_is_blocked_and_final_answer_forced(self) -> None:
        responses = [tool_call("one", "q1"), tool_call("two", "q2"), tool_call("three", "q3"), FakeResponse([], "done")]
        result, client, provider = self.run_search(responses)
        self.assertEqual(provider.queries, ["q1", "q2"])
        self.assertEqual(result.response.output_text, "done")
        self.assertEqual(client.responses.requests[-1]["tool_choice"], "none")
        self.assertIn("search_limit_reached", client.responses.requests[-1]["input"][-1]["output"])

    def test_bad_arguments_and_provider_error_are_returned_to_model(self) -> None:
        bad_call = FakeResponse(
            [{"type": "function_call", "name": "web_search", "call_id": "bad", "arguments": "{"}]
        )
        result, client, _ = self.run_search([bad_call, FakeResponse([], "clarified")])
        self.assertEqual(result.response.output_text, "clarified")
        self.assertIn("invalid_arguments", client.responses.requests[1]["input"][-1]["output"])

        provider = RecordingProvider(SearchError("timeout", "Exa 搜索响应超时。"))
        _, client, _ = self.run_search([tool_call("call"), FakeResponse([], "unverified")], provider)
        self.assertIn("无法完成联网核验", client.responses.requests[1]["input"][-1]["output"])

    def test_unsupported_function_tools_are_reported(self) -> None:
        error = RuntimeError("tools are not supported")
        error.status_code = 400  # type: ignore[attr-defined]
        with self.assertRaises(SearchToolUnsupportedError):
            self.run_search([error])


if __name__ == "__main__":
    unittest.main()
