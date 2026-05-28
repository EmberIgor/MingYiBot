from __future__ import annotations

import json
from typing import Any

from nonebot import logger


def create_openai_client(api_key: str, base_url: str = "") -> Any | None:
    if not api_key:
        return None

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        logger.warning("AI client disabled because openai package is unavailable: {}", exc)
        return None

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    return AsyncOpenAI(**client_kwargs)


async def request_response(
    client: Any,
    model: str,
    instructions: str,
    messages: list[dict[str, str]],
    image_urls: list[str] | None = None,
    web_search: bool = False,
    stream: bool = False,
) -> Any:
    request_kwargs: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": build_responses_input(messages, image_urls),
        "stream": stream,
    }
    if web_search:
        request_kwargs["tools"] = [{"type": "web_search"}]
        request_kwargs["tool_choice"] = "auto"

    return await client.responses.create(**request_kwargs)


def build_responses_input(
    messages: list[dict[str, str]],
    image_urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    response_input: list[dict[str, Any]] = []
    image_urls = image_urls or []

    for index, item in enumerate(messages):
        role = item["role"]
        if role == "system":
            continue

        content_type = "output_text" if role == "assistant" else "input_text"
        content: list[dict[str, Any]] = [{"type": content_type, "text": item["content"]}]

        if role == "user" and index == len(messages) - 1:
            content.extend(
                {"type": "input_image", "image_url": image_url, "detail": "auto"}
                for image_url in image_urls
            )

        response_input.append({"role": role, "content": content})

    return response_input


def extract_content(response: Any) -> str:
    if isinstance(response, str):
        return _extract_sse_content(response)

    output_text = _get_value(response, "output_text")
    if output_text:
        return str(output_text)

    choices = _get_value(response, "choices") or []
    if choices:
        message = _get_value(choices[0], "message")
        content = _get_value(message, "content")
        if content:
            return str(content)

    text_parts: list[str] = []
    for item in _get_value(response, "output") or []:
        if _get_value(item, "type") != "message":
            continue
        for content_item in _get_value(item, "content") or []:
            text = _get_value(content_item, "text")
            if text:
                text_parts.append(str(text))

    return "\n".join(text_parts)


def is_retryable_error(exc: Exception) -> bool:
    status_code: Any = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)

    if not isinstance(status_code, int):
        return True

    if status_code in {408, 409, 429}:
        return True

    return status_code >= 500


def response_preview(response: Any) -> str:
    if hasattr(response, "model_dump"):
        try:
            response = response.model_dump()
        except Exception:
            pass

    preview = repr(response)
    if len(preview) > 1000:
        return preview[:1000] + "...<truncated>"
    return preview


def _extract_sse_content(response: str) -> str:
    text_deltas: list[str] = []
    completed_text = ""

    for line in response.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue

        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue

        event_type = str(data.get("type", ""))
        if event_type.endswith(".delta") and "delta" in data:
            text_deltas.append(str(data["delta"]))
            continue

        if event_type.endswith(".done") and data.get("text"):
            completed_text = str(data["text"])
            continue

        nested_response = data.get("response")
        if nested_response:
            nested_text = extract_content(nested_response)
            if nested_text:
                completed_text = nested_text

    return completed_text or "".join(text_deltas)


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
