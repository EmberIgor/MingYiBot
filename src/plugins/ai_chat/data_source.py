from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from nonebot import logger

from .config import Config
from .memory_store import MemoryStore
from .role_store import RoleStore


class ChatHandler:
    def __init__(self, config: Config, role_store: RoleStore, memory_store: MemoryStore | None = None) -> None:
        self.config = config
        self.role_store = role_store
        self.client: Any | None = self._create_client()
        self.memory_store = memory_store or self._create_memory_store()
        self.histories: dict[str, list[dict[str, str]]] = {}
        self.last_active_at: dict[str, float] = {}
        self.memory_turn_counts: dict[str, int] = {}

    async def ask(
        self,
        message: str,
        session_id: str,
        role_name: str,
        image_urls: list[str] | None = None,
        memory_scope: str | None = None,
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
        memories = self._memory_items(memory_scope)

        for retry in range(3):
            try:
                response = await self._request_ai(system_prompt, history, image_urls or [], memories)
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
        self._schedule_memory_summary_if_needed(memory_scope, self.histories[session_id])
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

    def memory_enabled(self) -> bool:
        return self.config.aichat_memory_enabled and self.memory_store is not None

    def list_memories(self, memory_scope: str) -> list[dict[str, str]]:
        if not self.memory_enabled():
            return []
        return self.memory_store.list_memories(memory_scope)

    def remember(self, memory_scope: str, content: str) -> dict[str, str] | None:
        if not self.memory_enabled():
            return None
        return self.memory_store.add_memory(memory_scope, content)

    def forget(self, memory_scope: str, memory_id: str) -> bool:
        if not self.memory_enabled():
            return False
        return self.memory_store.delete_memory(memory_scope, memory_id)

    def clear_memories(self, memory_scope: str) -> int:
        if not self.memory_enabled():
            return 0
        return self.memory_store.clear_memories(memory_scope)

    def _memory_items(self, memory_scope: str | None) -> list[dict[str, str]]:
        if not memory_scope or not self.memory_enabled():
            return []
        return self.memory_store.list_memories(memory_scope)

    def _schedule_memory_summary_if_needed(
        self,
        memory_scope: str | None,
        history: list[dict[str, str]],
    ) -> None:
        if not memory_scope or not self.memory_enabled():
            return

        interval = self.config.aichat_memory_summary_interval
        if interval <= 0:
            return

        self.memory_turn_counts[memory_scope] = self.memory_turn_counts.get(memory_scope, 0) + 1
        if self.memory_turn_counts[memory_scope] % interval != 0:
            return

        recent_turns = self._recent_turns(history, max_turns=3)
        if not recent_turns:
            return

        self._schedule_memory_summary(memory_scope, recent_turns)

    def _schedule_memory_summary(self, memory_scope: str, recent_turns: list[dict[str, str]]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("AI memory summary skipped because no running event loop is available")
            return

        loop.create_task(self._summarize_memory(memory_scope, recent_turns))

    async def _summarize_memory(self, memory_scope: str, recent_turns: list[dict[str, str]]) -> None:
        if not self.client or not self.config.aichat_model or not self.memory_enabled():
            return

        try:
            response = await self.client.responses.create(
                model=self.config.aichat_model,
                instructions=self._memory_summary_instructions(),
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": self._format_memory_summary_input(recent_turns),
                            }
                        ],
                    }
                ],
                stream=False,
            )
            for memory in self._extract_memory_summaries(response):
                self.memory_store.add_memory(memory_scope, memory)
        except Exception as exc:
            logger.exception("AI memory summary failed: {}", exc)

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

    def _recent_turns(self, history: list[dict[str, str]], max_turns: int) -> list[dict[str, str]]:
        non_system = [item.copy() for item in history if item.get("role") in {"user", "assistant"}]
        return non_system[-max_turns * 2 :]

    def _memory_summary_instructions(self) -> str:
        return (
            "你负责从 QQ 聊天中提炼长期记忆。只记录用户长期偏好、身份背景、稳定事实、持续目标。"
            "不要记录新闻、天气、价格、政策、活动、日期相关状态等易变信息。"
            "不要记录图片 URL，也不要因为出现 [image] 就记忆图片内容。"
            "如果没有值得长期记住的信息，返回 {\"memories\":[],\"forget\":[]}。"
            "只输出 JSON，格式必须是 {\"memories\":[\"短记忆\"],\"forget\":[]}。"
        )

    def _format_memory_summary_input(self, recent_turns: list[dict[str, str]]) -> str:
        lines = ["请从以下最近对话中提炼可长期保存的用户记忆："]
        for item in recent_turns:
            role = "用户" if item["role"] == "user" else "AI"
            lines.append(f"{role}: {item['content']}")
        return "\n".join(lines)

    def _extract_memory_summaries(self, response: Any) -> list[str]:
        content = self._extract_content(response).strip()
        if not content:
            return []

        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                logger.warning("AI memory summary returned non-JSON content: {}", content[:300])
                return []
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("AI memory summary returned invalid JSON: {}", content[:300])
                return []

        memories = payload.get("memories") if isinstance(payload, dict) else []
        if not isinstance(memories, list):
            return []

        return [str(memory).strip() for memory in memories if str(memory).strip()]

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
        memories: list[dict[str, str]] | None = None,
    ) -> Any:
        request_kwargs: dict[str, Any] = {
            "model": self.config.aichat_model,
            "instructions": self._build_instructions(system_prompt, memories),
            "input": self._responses_input(history, image_urls),
            "stream": False,
        }
        if self.config.aichat_web_search:
            request_kwargs["tools"] = [{"type": "web_search"}]
            request_kwargs["tool_choice"] = "auto"

        return await self.client.responses.create(**request_kwargs)

    def _build_instructions(self, role_prompt: str, memories: list[dict[str, str]] | None = None) -> str:
        now = datetime.now(timezone(timedelta(hours=8), "HKT")).strftime("%Y-%m-%d %H:%M:%S %Z")
        realtime_rule = (
            "当用户询问今天、现在、最近、天气、新闻、价格、政策、活动、产品发售等可能变化的信息时，"
            "必须按当前日期时间理解问题；如果联网工具可用，应先查询或核验再回答。"
            "不要凭记忆编造日期、天气、新闻或其他实时事实；无法确认时直接说明无法确认。"
        )
        style_rule = "回答应适合 QQ 聊天：简洁、自然、直接；不要使用 Markdown 加粗，除非用户明确需要格式化。"
        memory_text = self._format_memory_instructions(memories or [])
        return "\n".join(
            item
            for item in [
                role_prompt.strip(),
                "",
                f"当前日期时间：{now}。",
                realtime_rule,
                style_rule,
                memory_text,
            ]
            if item
        )

    def _format_memory_instructions(self, memories: list[dict[str, str]]) -> str:
        if not memories:
            return ""

        lines = [
            "",
            "已知用户长期记忆（只用于理解用户偏好、背景和长期目标；不要把它们当作实时事实来源）：",
        ]
        lines.extend(f"{index}. {item['content']}" for index, item in enumerate(memories, 1))
        return "\n".join(lines)

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

    def _create_memory_store(self) -> MemoryStore | None:
        if not self.config.aichat_memory_enabled:
            return None
        return MemoryStore(self.config.aichat_memory_path, self.config.aichat_memory_max_items)

    def _touch(self, session_id: str) -> None:
        self.last_active_at[session_id] = time.time()
