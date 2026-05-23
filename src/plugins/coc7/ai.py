from typing import Any

from nonebot import logger

from .config import Config


class RuleAnswerer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client: Any | None = self._create_client()

    async def answer(self, question: str) -> str:
        if not question.strip():
            return "请在 /coc 后输入问题。"
        if not self.client or not self.config.effective_ai_model:
            return "COC7 AI 助手还没有配置好，请设置 COC7_AI_KEY、COC7_AI_BASEURL 和 COC7_AI_MODEL，或复用 AICHAT_* 配置。"

        messages = [
            {
                "role": "system",
                "content": (
                    "你是 COC7 规则助手。优先依据你已集成的 COC 资料库回答。"
                    "回答要适合 QQ 群聊，简短、清楚。"
                    "如果资料库中没有可靠依据，不要编造规则，要明确说明不确定。"
                ),
            },
            {"role": "user", "content": question.strip()},
        ]
        try:
            response = await self.client.chat.completions.create(
                model=self.config.effective_ai_model,
                messages=messages,
                stream=False,
            )
        except Exception as exc:
            logger.exception("COC7 rule answer request failed: {}", exc)
            return "COC7 AI 助手请求失败，请稍后再试。"

        content = (response.choices[0].message.content or "").strip()
        return content or "COC7 AI 助手没有返回内容。"

    def _create_client(self) -> Any | None:
        if not self.config.effective_ai_key or not self.config.effective_ai_baseurl:
            return None
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            logger.warning("COC7 rule answer client disabled because openai package is unavailable: {}", exc)
            return None
        return AsyncOpenAI(
            api_key=self.config.effective_ai_key,
            base_url=self.config.effective_ai_baseurl,
        )
