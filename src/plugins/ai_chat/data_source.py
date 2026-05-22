import re
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

    async def ask(self, message: str, session_id: str, role_name: str) -> str:
        if not self.client or not self.config.aichat_model:
            return "AI 聊天还没有配置好，请设置 AICHAT_KEY、AICHAT_BASEURL 和 AICHAT_MODEL。"

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
                response = await self.client.chat.completions.create(
                    model=self.config.aichat_model,
                    messages=history,
                    stream=False,
                )
                break
            except Exception as exc:
                if retry == 2:
                    history.pop()
                    logger.exception("AI chat request failed: {}", exc)
                    return "AI 聊天请求失败，请稍后再试。"
        else:
            history.pop()
            return "AI 聊天请求失败，请稍后再试。"

        content = response.choices[0].message.content or ""
        content = re.sub(r"^[\r\n]+|[\r\n]+$", "", content.strip())
        history.append({"role": "assistant", "content": content})
        self._trim_history(session_id, system_prompt)
        return content

    def clear_history(self, session_id: str | None = None) -> None:
        if session_id is None:
            self.histories.clear()
            return

        self.histories.pop(session_id, None)

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

        try:
            from openai import AsyncOpenAI
        except ImportError:
            return None

        return AsyncOpenAI(
            api_key=self.config.aichat_key,
            base_url=self.config.aichat_baseurl,
        )
