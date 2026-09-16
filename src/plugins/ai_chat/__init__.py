from __future__ import annotations

from nonebot import get_plugin_config, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.event import Reply
from nonebot.plugin import PluginMetadata

from src.common.rules import directed_to_bot
from src.common.settings import get_runtime_settings_store

from .config import Config
from .data_source import ChatHandler


__plugin_meta__ = PluginMetadata(
    name="ai_chat",
    description="在机器人被 @ 或收到私聊时提供 AI 对话",
    usage="@机器人 聊天内容",
    config=Config,
)

config = get_plugin_config(Config)
runtime_settings = get_runtime_settings_store()
chat_handler = ChatHandler(config)
ai_chat = on_message(directed_to_bot(), priority=100, block=True)


def _extract_chat_content(message: Message, bot: Bot) -> tuple[str, list[str]]:
    parts: list[str] = []
    image_urls: list[str] = []
    for segment in message:
        if segment.type == "text":
            text = segment.data.get("text", "").strip()
            if text:
                parts.append(text)
        elif segment.type == "at":
            qq = str(segment.data.get("qq", ""))
            if qq and qq != str(bot.self_id):
                parts.append(f"@{qq}")
        elif segment.type == "image":
            image_url = str(segment.data.get("url") or segment.data.get("file") or "").strip()
            if image_url.startswith(("http://", "https://", "data:")):
                image_urls.append(image_url)
            parts.append("[image]")
        elif segment.type == "reply":
            continue
        else:
            parts.append(f"[{segment.type}]")
    return " ".join(parts).strip(), image_urls


def _reply_sender_name(reply: Reply) -> str:
    sender = reply.sender
    return str(sender.card or sender.nickname or sender.user_id or "未知用户")


def _extract_reply_context(reply: Reply | None, bot: Bot) -> tuple[str, list[str]]:
    if reply is None:
        return "", []
    quoted_content, image_urls = _extract_chat_content(reply.message, bot)
    quoted_content = quoted_content or "[空消息]"
    return (
        f"用户引用了 QQ {reply.sender.user_id}（{_reply_sender_name(reply)}）的消息：{quoted_content}",
        image_urls,
    )


def _build_prompt_with_reply(prompt: str, reply_context: str) -> str:
    if not reply_context:
        return prompt
    return f"{reply_context}\n用户当前消息：{prompt}"


def _conversation_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"mingyi:qq:group:{event.group_id}:user:{event.user_id}"
    return f"mingyi:qq:private:user:{event.user_id}"


def _display_name(event: MessageEvent) -> str:
    sender = event.sender
    return str(getattr(sender, "card", "") or getattr(sender, "nickname", "") or event.user_id)


async def _fallback_web_search_enabled(event: MessageEvent) -> bool:
    return await runtime_settings.get_bool_async(
        "ai_chat",
        "web_search",
        config.aichat_web_search,
        group_id=event.group_id if isinstance(event, GroupMessageEvent) else None,
        user_id=event.user_id,
    )


@ai_chat.handle()
async def handle_ai_chat(bot: Bot, event: MessageEvent) -> None:
    prompt, image_urls = _extract_chat_content(event.get_message(), bot)
    reply_context, reply_image_urls = _extract_reply_context(event.reply, bot)
    prompt = _build_prompt_with_reply(prompt or "你好", reply_context)
    response = await chat_handler.ask(
        prompt,
        _conversation_id(event),
        user_id=event.user_id,
        display_name=_display_name(event),
        group_id=event.group_id if isinstance(event, GroupMessageEvent) else None,
        image_urls=[*reply_image_urls, *image_urls],
        web_search=await _fallback_web_search_enabled(event),
    )
    await ai_chat.finish(MessageSegment.text(response), at_sender=True)
