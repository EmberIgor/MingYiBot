from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from nonebot import logger

from .config import Config
from .role_store import RoleStore


class ChatHandler:
    def __init__(self, config: Config, role_store: RoleStore) -> None:
        self.config = config
        self.role_store = role_store
        self.client: Any | None = self._create_client()
        self.histories: dict[str, list[dict[str, str]]] = {}
        self.last_active_at: dict[str, float] = {}

    async def ask(
        self,
        message: str,
        session_id: str,
        role_name: str,
        image_urls: list[str] | None = None,
    ) -> str:
        self.cleanup_expired()

        if not self.client or not self.config.aichat_model:
            return "AI 聊天还没有配置好，请设置 AICHAT_KEY 和 AICHAT_MODEL。"

        self._touch(session_id)
        system_prompt = self.role_store.get_prompt(role_name)
        history = self.histories.setdefault(
            session_id,
            [{"role": "system", "content": system_prompt}],
        )
        if history[0]["content"] != system_prompt:
            history[:] = [{"role": "system", "content": system_prompt}]

        history.append({"role": "user", "content": message})

        for retry in range(3):
            try:
                response = await self._request_ai(system_prompt, history, image_urls or [])
                break
            except Exception as exc:
                if retry == 2 or not self._is_retryable_error(exc):
                    history.pop()
                    logger.exception("AI chat request failed: {}", exc)
                    return "AI 聊天请求失败，请稍后再试。"
                await asyncio.sleep(0.5 * (retry + 1))
        else:
            history.pop()
            return "AI 聊天请求失败，请稍后再试。"

        content = self._extract_content(response)
        content = re.sub(r"^[\r\n]+|[\r\n]+$", "", content.strip())
        if not content:
            logger.warning("AI chat response had no extractable text: {}", self._response_preview(response))
            history.pop()
            return "AI 没有返回可发送的内容，请稍后再试。"

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

        max_non_system_messages = max(history_limit - 1, 2)
        max_non_system_messages = max_non_system_messages // 2 * 2
        kept_messages = history[1:][-max_non_system_messages:]
        while kept_messages and kept_messages[0]["role"] == "assistant":
            kept_messages = kept_messages[1:]

        self.histories[session_id] = [
            {"role": "system", "content": system_prompt},
            *kept_messages,
        ]

    def _is_retryable_error(self, exc: Exception) -> bool:
        status_code: Any = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)

        if not isinstance(status_code, int):
            return True

        if status_code in {408, 409, 429}:
            return True

        return status_code >= 500

    async def _request_ai(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        image_urls: list[str],
    ) -> Any:
        request_kwargs: dict[str, Any] = {
            "model": self.config.aichat_model,
            "instructions": self._build_instructions(system_prompt),
            "input": self._responses_input(history, image_urls),
            "stream": False,
        }
        if self.config.aichat_web_search:
            request_kwargs["tools"] = [{"type": "web_search"}]
            request_kwargs["tool_choice"] = "auto"

        return await self.client.responses.create(**request_kwargs)

    def _build_instructions(self, role_prompt: str) -> str:
        now = datetime.now(timezone(timedelta(hours=8), "HKT")).strftime("%Y-%m-%d %H:%M:%S %Z")
        realtime_rule = (
            "当用户询问今天、现在、最近、天气、新闻、价格、政策、活动、产品发售等可能变化的信息时，"
            "必须按当前日期时间理解问题；如果联网工具可用，应先查询或核验再回答。"
            "不要凭记忆编造日期、天气、新闻或其他实时事实；无法确认时直接说明无法确认。"
        )
        style_rule = "回答应适合 QQ 聊天：简洁、自然、直接；不要使用 Markdown 加粗，除非用户明确需要格式化。"
        return "\n".join(
            [
                role_prompt.strip(),
                "",
                f"当前日期时间：{now}。",
                realtime_rule,
                style_rule,
            ]
        )

    def _responses_input(
        self,
        history: list[dict[str, str]],
        image_urls: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        response_input: list[dict[str, Any]] = []
        image_urls = image_urls or []

        for index, item in enumerate(history):
            role = item["role"]
            if role == "system":
                continue

            content_type = "output_text" if role == "assistant" else "input_text"
            content: list[dict[str, Any]] = [{"type": content_type, "text": item["content"]}]

            if role == "user" and index == len(history) - 1:
                content.extend(
                    {"type": "input_image", "image_url": image_url, "detail": "auto"}
                    for image_url in image_urls
                )

            response_input.append({"role": role, "content": content})

        return response_input

    def _extract_content(self, response: Any) -> str:
        if isinstance(response, str):
            return self._extract_sse_content(response)

        output_text = self._get_value(response, "output_text")
        if output_text:
            return str(output_text)

        choices = self._get_value(response, "choices") or []
        if choices:
            message = self._get_value(choices[0], "message")
            content = self._get_value(message, "content")
            if content:
                return str(content)

        text_parts: list[str] = []
        for item in self._get_value(response, "output") or []:
            if self._get_value(item, "type") != "message":
                continue
            for content_item in self._get_value(item, "content") or []:
                text = self._get_value(content_item, "text")
                if text:
                    text_parts.append(str(text))

        return "\n".join(text_parts)

    def _extract_sse_content(self, response: str) -> str:
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
                nested_text = self._extract_content(nested_response)
                if nested_text:
                    completed_text = nested_text

        return completed_text or "".join(text_deltas)

    def _get_value(self, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)

    def _response_preview(self, response: Any) -> str:
        if hasattr(response, "model_dump"):
            try:
                response = response.model_dump()
            except Exception:
                pass

        preview = repr(response)
        if len(preview) > 1000:
            return preview[:1000] + "...<truncated>"
        return preview

    def _create_client(self) -> Any | None:
        if not self.config.aichat_key:
            return None

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            logger.warning("AI chat client disabled because openai package is unavailable: {}", exc)
            return None

        client_kwargs = {"api_key": self.config.aichat_key}
        if self.config.aichat_baseurl:
            client_kwargs["base_url"] = self.config.aichat_baseurl

        return AsyncOpenAI(**client_kwargs)

    def _touch(self, session_id: str) -> None:
        self.last_active_at[session_id] = time.time()
