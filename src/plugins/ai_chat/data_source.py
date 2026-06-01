from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from nonebot import logger
from src.common.ai import (
    create_openai_client,
    extract_content,
    is_retryable_error,
    request_response,
    response_preview,
)

from .config import Config
from .memory_store import MemoryStore, MemoryStoreError, MySQLMemoryStore, UnavailableMemoryStore
from .role_store import RoleStore


class ChatHandler:
    def __init__(self, config: Config, role_store: RoleStore, memory_store: Any | None = None) -> None:
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
        web_search: bool | None = None,
    ) -> str:
        self.cleanup_expired()

        if not self.client or not self.config.resolved_ai_model:
            return "AI 聊天还没有配置好，请设置 AICHAT_KEY/AICHAT_MODEL 或 AI_KEY/AI_MODEL。"

        self._touch(session_id)
        system_prompt = self.role_store.get_prompt(role_name)
        history = self.histories.setdefault(
            session_id,
            [{"role": "system", "content": system_prompt}],
        )
        if history[0]["content"] != system_prompt:
            history[:] = [{"role": "system", "content": system_prompt}]

        history.append({"role": "user", "content": message})
        memories = await self._memory_items(memory_scope)

        for retry in range(3):
            try:
                response = await self._request_ai(
                    system_prompt,
                    history,
                    image_urls or [],
                    memories,
                    web_search=web_search,
                )
                break
            except Exception as exc:
                if retry == 2 or not is_retryable_error(exc):
                    history.pop()
                    logger.exception("AI chat request failed: {}", exc)
                    return "AI 聊天请求失败，请稍后再试。"
                await asyncio.sleep(0.5 * (retry + 1))
        else:
            history.pop()
            return "AI 聊天请求失败，请稍后再试。"

        content = extract_content(response)
        content = re.sub(r"^[\r\n]+|[\r\n]+$", "", content.strip())
        if not content:
            logger.warning("AI chat response had no extractable text: {}", response_preview(response))
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

    async def list_memories_async(self, memory_scope: str) -> list[dict[str, str]]:
        if not self.memory_enabled():
            return []
        return await self._call_memory_store(self.memory_store.list_memories, memory_scope)

    def remember(self, memory_scope: str, content: str) -> dict[str, str] | None:
        if not self.memory_enabled():
            return None
        return self.memory_store.add_memory(memory_scope, content)

    async def remember_async(
        self,
        memory_scope: str,
        content: str,
        *,
        source: str = "manual",
        category: str = "general",
        confidence: float = 1.0,
    ) -> dict[str, str] | None:
        if not self.memory_enabled():
            return None
        return await self._call_memory_store(
            self.memory_store.add_memory,
            memory_scope,
            content,
            source=source,
            category=category,
            confidence=confidence,
        )

    def forget(self, memory_scope: str, memory_id: str) -> bool:
        if not self.memory_enabled():
            return False
        return self.memory_store.delete_memory(memory_scope, memory_id)

    async def forget_async(self, memory_scope: str, memory_id: str) -> bool:
        if not self.memory_enabled():
            return False
        return await self._call_memory_store(self.memory_store.delete_memory, memory_scope, memory_id)

    def clear_memories(self, memory_scope: str) -> int:
        if not self.memory_enabled():
            return 0
        return self.memory_store.clear_memories(memory_scope)

    async def clear_memories_async(self, memory_scope: str) -> int:
        if not self.memory_enabled():
            return 0
        return await self._call_memory_store(self.memory_store.clear_memories, memory_scope)

    def compact_memories(self, memory_scope: str) -> dict[str, int]:
        if not self.memory_enabled():
            return {"kept": 0, "removed": 0}
        return self.memory_store.compact_memories(memory_scope)

    async def compact_memories_async(self, memory_scope: str) -> dict[str, int]:
        if not self.memory_enabled():
            return {"kept": 0, "removed": 0}
        return await self._call_memory_store(self.memory_store.compact_memories, memory_scope)

    async def organize_memories_async(self, memory_scope: str) -> dict[str, int | str]:
        if not self.memory_enabled():
            return {"kept": 0, "removed": 0, "mode": "local"}

        existing_memories = await self._memory_items(memory_scope)
        if len(existing_memories) <= 1:
            return {"kept": len(existing_memories), "removed": 0, "mode": "none"}

        if not self.client or not self.config.resolved_ai_model:
            result = await self.compact_memories_async(memory_scope)
            return {**result, "mode": "local"}

        try:
            response = await request_response(
                self.client,
                model=self.config.resolved_ai_model,
                instructions=self._memory_organize_instructions(),
                messages=[
                    {
                        "role": "user",
                        "content": self._format_memory_organize_input(existing_memories),
                    }
                ],
                stream=False,
            )
            organized_memories = self._extract_memory_summaries(response)
            if not organized_memories:
                result = await self.compact_memories_async(memory_scope)
                return {**result, "mode": "local"}

            result = await self._call_memory_store(
                self.memory_store.replace_memories,
                memory_scope,
                organized_memories[: self.config.aichat_memory_max_items],
                source="manual",
                category="organized",
                confidence=0.9,
            )
            return {**result, "mode": "ai"}
        except Exception as exc:
            logger.warning("AI memory organize fell back to local compaction: {}", exc)
            result = await self.compact_memories_async(memory_scope)
            return {**result, "mode": "local"}

    async def _memory_items(self, memory_scope: str | None) -> list[dict[str, str]]:
        if not memory_scope or not self.memory_enabled():
            return []
        try:
            return await self.list_memories_async(memory_scope)
        except MemoryStoreError as exc:
            logger.warning("AI memory lookup skipped: {}", exc)
            return []

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
        if not self.client or not self.config.resolved_ai_model or not self.memory_enabled():
            return

        try:
            existing_memories = await self._memory_items(memory_scope)
            response = await request_response(
                self.client,
                model=self.config.resolved_ai_model,
                instructions=self._memory_summary_instructions(),
                messages=[
                    {
                        "role": "user",
                        "content": self._format_memory_summary_input(recent_turns, existing_memories),
                    }
                ],
                stream=False,
            )
            for memory in self._extract_memory_summaries(response):
                source = self._memory_summary_source(memory, recent_turns)
                await self.remember_async(
                    memory_scope,
                    memory,
                    source=source,
                    category="profile",
                    confidence=0.95 if source == "explicit_chat" else 0.7,
                )
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
            "如果现有长期记忆已经覆盖了同一信息，不要重复输出；只有更明确、更具体或用户明确改口时才输出新记忆。"
            "不要记录新闻、天气、价格、政策、活动、日期相关状态等易变信息。"
            "不要记录图片 URL，也不要因为出现 [image] 就记忆图片内容。"
            "普通聊天话题不等于长期记忆，不要把“用户聊到了某主题”保存为记忆。"
            "如果没有值得长期记住的信息，返回 {\"memories\":[],\"forget\":[]}。"
            "只输出 JSON，格式必须是 {\"memories\":[\"短记忆\"],\"forget\":[]}。"
        )

    def _memory_organize_instructions(self) -> str:
        return (
            "你负责整理用户现有长期记忆。合并重复或高度相似的条目，删除空泛、临时、过期、互相矛盾的旧条目。"
            "如果多条记忆冲突，保留更明确、更具体、更像用户当前偏好的条目；不要编造列表中没有的信息。"
            "保留用户明确要求机器人遵守的稳定偏好、称呼、背景和长期目标。"
            "输出条目要短、具体、可直接作为长期记忆使用。"
            "只输出 JSON，格式必须是 {\"memories\":[\"整理后的短记忆\"],\"forget\":[]}。"
        )

    def _format_memory_summary_input(
        self,
        recent_turns: list[dict[str, str]],
        existing_memories: list[dict[str, str]] | None = None,
    ) -> str:
        lines = ["请从以下最近对话中提炼可长期保存的用户记忆："]
        if existing_memories:
            lines.append("当前已有长期记忆：")
            lines.extend(f"- {item['content']}" for item in existing_memories)
            lines.append("最近对话：")
        for item in recent_turns:
            role = "用户" if item["role"] == "user" else "AI"
            lines.append(f"{role}: {item['content']}")
        return "\n".join(lines)

    def _format_memory_organize_input(self, memories: list[dict[str, str]]) -> str:
        lines = ["请整理以下长期记忆，只返回整理后的当前有效记忆："]
        lines.extend(f"{index}. {item['content']}" for index, item in enumerate(memories, 1))
        return "\n".join(lines)

    def _memory_summary_source(self, memory: str, recent_turns: list[dict[str, str]]) -> str:
        user_text = "\n".join(item["content"] for item in recent_turns if item.get("role") == "user")
        explicit_patterns = (
            r"(以后|之后|往后|从现在|从今).{0,30}(叫我|称呼我|叫|称呼|记住|不要|改成)",
            r"(叫我|称呼我|把我叫作|把我的.{0,10}改成|我的称呼改成)",
            r"(记住|请记住).{0,80}(我|我的|以后|偏好|喜欢|不喜欢|叫|称呼)",
        )
        if any(re.search(pattern, user_text) for pattern in explicit_patterns):
            return "explicit_chat"
        return "summary"

    def _extract_memory_summaries(self, response: Any) -> list[str]:
        content = extract_content(response).strip()
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

    async def _request_ai(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        image_urls: list[str],
        memories: list[dict[str, str]] | None = None,
        web_search: bool | None = None,
    ) -> Any:
        return await request_response(
            self.client,
            model=self.config.resolved_ai_model,
            instructions=self._build_instructions(system_prompt, memories),
            messages=history,
            image_urls=image_urls,
            web_search=self.config.aichat_web_search if web_search is None else web_search,
            stream=False,
        )

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

    async def _call_memory_store(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(func, *args, **kwargs)

    def _create_client(self) -> Any | None:
        return create_openai_client(self.config.resolved_ai_key, self.config.resolved_ai_baseurl)

    def _create_memory_store(self) -> Any | None:
        if not self.config.aichat_memory_enabled:
            return None

        backend = self.config.aichat_memory_backend.strip().lower()
        if backend == "json":
            return MemoryStore(self.config.aichat_memory_path, self.config.aichat_memory_max_items)
        if backend != "mysql":
            logger.warning("Unknown AI memory backend: {}", self.config.aichat_memory_backend)
            return UnavailableMemoryStore("长期记忆数据库暂不可用，请检查 MySQL 配置。")

        try:
            return MySQLMemoryStore(
                host=self.config.mysql_host,
                port=self.config.mysql_port,
                database=self.config.mysql_database,
                user=self.config.mysql_user,
                password=self.config.mysql_password,
                connect_timeout_seconds=self.config.mysql_connect_timeout_seconds,
                max_items=self.config.aichat_memory_max_items,
                import_path=self.config.aichat_memory_path,
            )
        except MemoryStoreError as exc:
            logger.warning("AI memory MySQL backend unavailable: {}", exc)
            return UnavailableMemoryStore("长期记忆数据库暂不可用，请检查 MySQL 配置。")

    def _touch(self, session_id: str) -> None:
        self.last_active_at[session_id] = time.time()
