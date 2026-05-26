from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import time
from typing import Any, Union
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from nonebot import logger

from .config import Config
from .role_store import RoleStore

ChatContent = Union[str, list[dict[str, Any]]]
ChatMessage = dict[str, Any]
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 15.0
RESPONSES_API_TIMEOUT_SECONDS = 60.0


class ChatHandler:
    def __init__(self, config: Config, role_store: RoleStore) -> None:
        self.config = config
        self.role_store = role_store
        self.client: Any | None = self._create_client()
        self.histories: dict[str, list[ChatMessage]] = {}
        self.last_active_at: dict[str, float] = {}

    async def ask(
        self,
        message: ChatContent,
        session_id: str,
        role_name: str,
        history_message: str | None = None,
    ) -> str:
        self.cleanup_expired()

        if not self.config.aichat_model:
            return "AI 聊天还没有配置好，请设置 AICHAT_KEY、AICHAT_BASEURL 和 AICHAT_MODEL。"
        if self._web_search_enabled() and (not self.config.aichat_key or not self.config.aichat_baseurl):
            return "AI 联网搜索还没有配置好，请设置 AICHAT_KEY、AICHAT_BASEURL 和 AICHAT_MODEL。"
        if not self._web_search_enabled() and not self.client:
            return "AI 聊天还没有配置好，请设置 AICHAT_KEY、AICHAT_BASEURL 和 AICHAT_MODEL。"

        self._touch(session_id)
        system_prompt = self.role_store.get_prompt(role_name)
        history = self.histories.setdefault(
            session_id,
            [{"role": "system", "content": system_prompt}],
        )
        if history[0]["content"] != system_prompt:
            history[:] = [{"role": "system", "content": system_prompt}]

        request_message = await self._prepare_message_content(message)
        request_messages = [
            *history,
            {"role": "user", "content": request_message},
        ]

        for retry in range(3):
            try:
                if self._web_search_enabled():
                    response = await self._create_response_with_web_search(request_messages, system_prompt)
                    content = _extract_responses_text(response)
                else:
                    response = await self.client.chat.completions.create(
                        model=self.config.aichat_model,
                        messages=request_messages,
                        stream=False,
                    )
                    content = response.choices[0].message.content or ""
                break
            except Exception as exc:
                if retry == 2:
                    logger.exception("AI chat request failed: {}", exc)
                    return "AI 聊天请求失败，请稍后再试。"
        else:
            return "AI 聊天请求失败，请稍后再试。"

        content = re.sub(r"^[\r\n]+|[\r\n]+$", "", content.strip())
        history.append({"role": "user", "content": history_message or _history_text(message)})
        history.append({"role": "assistant", "content": content})
        self._trim_history(session_id, system_prompt)
        self._touch(session_id)
        return content

    def clear_history(self, session_id: str | None = None) -> None:
        if session_id is None:
            self.histories.clear()
            self.last_active_at.clear()
            return

        self.histories.pop(session_id, None)
        self.last_active_at.pop(session_id, None)

    def cleanup_expired(self) -> int:
        ttl_seconds = self.config.aichat_session_ttl_minutes * 60
        if ttl_seconds <= 0:
            return 0

        expires_before = time.time() - ttl_seconds
        expired_session_ids = [
            session_id
            for session_id, last_active_at in self.last_active_at.items()
            if last_active_at < expires_before
        ]
        for session_id in expired_session_ids:
            self.clear_history(session_id)

        if expired_session_ids:
            logger.info("Cleaned {} expired AI chat sessions", len(expired_session_ids))

        return len(expired_session_ids)

    def _trim_history(self, session_id: str, system_prompt: str) -> None:
        history_limit = max(self.config.aichat_history_limit, 2)
        history = self.histories[session_id]
        if len(history) <= history_limit:
            return

        self.histories[session_id] = [
            {"role": "system", "content": system_prompt},
            *history[-(history_limit - 1) :],
        ]

    def _create_client(self) -> Any | None:
        if not self.config.aichat_key or not self.config.aichat_baseurl:
            return None
        if self._web_search_enabled():
            return None

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            logger.warning("AI chat client disabled because openai package is unavailable: {}", exc)
            return None

        return AsyncOpenAI(
            api_key=self.config.aichat_key,
            base_url=_normalize_openai_base_url(self.config.aichat_baseurl),
        )

    def _touch(self, session_id: str) -> None:
        self.last_active_at[session_id] = time.time()

    async def _prepare_message_content(self, message: ChatContent) -> ChatContent:
        if isinstance(message, str):
            return message

        if getattr(self.config, "aichat_image_mode", "url") != "base64":
            return message

        max_bytes = getattr(self.config, "aichat_image_max_bytes", 5 * 1024 * 1024)
        return await _inline_image_urls(message, max_bytes)

    def _web_search_enabled(self) -> bool:
        return bool(getattr(self.config, "aichat_web_search_enabled", False))

    async def _create_response_with_web_search(
        self,
        messages: list[ChatMessage],
        system_prompt: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.aichat_model,
            "stream": False,
            "tools": [{"type": "web_search"}],
            "input": _responses_input_from_messages(messages),
        }
        if system_prompt:
            payload["instructions"] = system_prompt

        max_tool_calls = int(getattr(self.config, "aichat_web_search_max_tool_calls", 1) or 0)
        if max_tool_calls > 0:
            payload["max_tool_calls"] = max_tool_calls

        return await asyncio.to_thread(
            _post_responses_request,
            _responses_api_url(self.config.aichat_baseurl),
            self.config.aichat_key,
            payload,
        )


def _history_text(message: ChatContent) -> str:
    if isinstance(message, str):
        return message

    parts: list[str] = []
    for part in message:
        if part.get("type") == "text":
            text = str(part.get("text", "")).strip()
            if text:
                parts.append(text)
        elif part.get("type") == "image_url":
            parts.append("[image]")
        else:
            parts.append(f"[{part.get('type', 'unknown')}]")

    return " ".join(parts).strip() or "你好"


def _responses_input_from_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    response_messages: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            continue

        response_messages.append(
            {
                "type": "message",
                "role": role,
                "content": _responses_content(message.get("content"), role),
            }
        )

    return response_messages


def _responses_content(content: Any, role: str) -> list[dict[str, Any]]:
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for part in content:
            if part.get("type") == "text":
                text = str(part.get("text", "")).strip()
                if text:
                    blocks.append({"type": "input_text", "text": text})
            elif part.get("type") == "image_url":
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    url = str(image_url.get("url") or "").strip()
                    if url:
                        blocks.append({"type": "input_image", "image_url": url})
        return blocks or [{"type": "input_text", "text": _history_text(content)}]

    block_type = "output_text" if role == "assistant" else "input_text"
    return [{"type": block_type, "text": str(content or "").strip() or "你好"}]


def _extract_responses_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = response.get("output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text)
        if texts:
            return "\n".join(texts)

    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content

    return ""


def _normalize_openai_base_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if not url:
        return url

    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")].rstrip("/")

    if parts.netloc == "api.gpt.ge" and not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"

    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _responses_api_url(base_url: str) -> str:
    url = _normalize_openai_base_url(base_url)
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
    path = f"{path}/responses" if path else "/responses"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _post_responses_request(url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "MingYiBot/ai-chat",
        },
        method="POST",
    )
    with urlopen(request, timeout=RESPONSES_API_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


async def _inline_image_urls(message: list[dict[str, Any]], max_bytes: int) -> list[dict[str, Any]]:
    inlined_message: list[dict[str, Any]] = []

    for part in message:
        if part.get("type") != "image_url":
            inlined_message.append(part)
            continue

        image_url = part.get("image_url")
        if not isinstance(image_url, dict):
            inlined_message.append(part)
            continue

        url = str(image_url.get("url") or "").strip()
        if not url or url.startswith("data:"):
            inlined_message.append(part)
            continue

        try:
            data_url = await asyncio.to_thread(_download_image_as_data_url, url, max_bytes)
        except Exception as exc:
            logger.warning("AI chat image inline failed, fallback to remote URL: {}", exc)
            inlined_message.append(part)
            continue

        inlined_message.append(
            {
                **part,
                "image_url": {
                    **image_url,
                    "url": data_url,
                },
            }
        )

    return inlined_message


def _download_image_as_data_url(url: str, max_bytes: int) -> str:
    request = Request(url, headers={"User-Agent": "MingYiBot/ai-chat"})
    with urlopen(request, timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS) as response:
        content_type = response.headers.get_content_type()
        data = response.read(max_bytes + 1)

    if len(data) > max_bytes:
        raise ValueError(f"image exceeds {max_bytes} bytes")

    if not content_type or content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(urlsplit(url).path)[0] or "image/jpeg"

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"
