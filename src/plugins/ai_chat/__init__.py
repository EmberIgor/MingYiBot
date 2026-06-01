from __future__ import annotations

import re

from nonebot import get_driver, get_plugin_config, logger, on_message, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.event import Reply
from nonebot.plugin import PluginMetadata
from src.common.rules import directed_to_bot
from src.common.settings import get_runtime_settings_store

from .config import Config
from .data_source import ChatHandler
from .memory_store import MemoryStoreError
from .role_store import RoleStore

__plugin_meta__ = PluginMetadata(
    name="ai_chat",
    description="在机器人被 @ 且未命中其他命令时提供 AI 聊天兜底能力",
    usage="@机器人 聊天内容\n.ai [角色名|列表|重载|重置|记忆|记住|忘记|整理记忆]",
    config=Config,
)

config = get_plugin_config(Config)
driver = get_driver()
runtime_settings = get_runtime_settings_store()
role_store = RoleStore(config.aichat_roles_path, config.aichat_default_role)
chat_handler = ChatHandler(config, role_store)
selected_roles: dict[str, str] = {}
MEMORY_UNAVAILABLE_TEXT = "长期记忆数据库暂不可用，请检查 MySQL 配置。"

role_command = on_regex(r"^[.。]ai(?:\s+|$)(.*)$", priority=20, block=True)
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
    sender_name = _reply_sender_name(reply)

    return f"用户引用了 {sender_name} 的消息：{quoted_content}", image_urls


def _build_prompt_with_reply(prompt: str, reply_context: str) -> str:
    if not reply_context:
        return prompt

    return f"{reply_context}\n用户当前消息：{prompt}"


def _conversation_scope(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}:user:{event.user_id}"
    return f"private:user:{event.user_id}"


def _current_role(scope: str, default_role: str) -> str:
    role_name = selected_roles.get(scope, default_role)
    if role_store.has_role(role_name):
        return role_name
    return default_role if role_store.has_role(default_role) else config.aichat_default_role


def _session_id(event: MessageEvent, default_role: str) -> str:
    scope = _conversation_scope(event)
    return f"{scope}:role:{_current_role(scope, default_role)}"


def _memory_scope(event: MessageEvent) -> str:
    return f"user:{event.user_id}"


def _group_id(event: MessageEvent) -> int | None:
    return event.group_id if isinstance(event, GroupMessageEvent) else None


def _is_superuser(event: MessageEvent) -> bool:
    user_id = str(event.user_id).strip()
    return user_id in {str(item).strip() for item in driver.config.superusers}


async def _default_role(event: MessageEvent) -> str:
    role_name = await runtime_settings.get_str_async(
        "ai_chat",
        "default_role",
        config.aichat_default_role,
        group_id=_group_id(event),
        user_id=event.user_id,
    )
    if role_store.has_role(role_name):
        return role_name
    return config.aichat_default_role


async def _web_search_enabled(event: MessageEvent) -> bool:
    return await runtime_settings.get_bool_async(
        "ai_chat",
        "web_search",
        config.aichat_web_search,
        group_id=_group_id(event),
        user_id=event.user_id,
    )


@role_command.handle()
async def handle_role_command(event: MessageEvent) -> None:
    await _handle_role_command(event, _parse_role_command(event.get_plaintext()), role_command)


def _parse_role_command(message: str) -> str:
    return re.sub(r"^[.。]ai(?:\s+|$)", "", message, count=1).strip()


def _parse_remember_command(command: str) -> str | None:
    for prefix in ("记住", "remember"):
        if command == prefix:
            return ""
        if command.startswith(f"{prefix} "):
            return command.removeprefix(prefix).strip()
    return None


def _parse_forget_command(command: str) -> str | None:
    for prefix in ("忘记", "forget"):
        if command == prefix:
            return ""
        if command.startswith(f"{prefix} "):
            return command.removeprefix(prefix).strip()
    return None


def _format_memory_list(memories: list[dict[str, str]]) -> str:
    if not memories:
        return "当前还没有长期记忆。"

    lines = ["当前长期记忆："]
    lines.extend(f"{item['id']}. {item['content']}" for item in memories)
    return "\n".join(lines)


async def _handle_role_command(event: MessageEvent, command: str, matcher) -> None:
    chat_handler.cleanup_expired()

    scope = _conversation_scope(event)
    memory_scope = _memory_scope(event)
    default_role = await _default_role(event)

    if not command or command in {"列表", "list"}:
        current = _current_role(scope, default_role)
        roles = "、".join(role_store.list_roles())
        await matcher.finish(f"当前角色：{current}\n可用角色：{roles}")

    if command in {"记忆", "memory"}:
        if not chat_handler.memory_enabled():
            await matcher.finish("AI 长期记忆未启用。")
        try:
            memories = await chat_handler.list_memories_async(memory_scope)
        except MemoryStoreError:
            await matcher.finish(MEMORY_UNAVAILABLE_TEXT)
        await matcher.finish(_format_memory_list(memories))

    if command in {"整理记忆", "整理长期记忆", "organize memory", "tidy memory", "compact memory"}:
        if not _is_superuser(event):
            await matcher.finish("只有管理员可以整理长期记忆。")
        if not chat_handler.memory_enabled():
            await matcher.finish("AI 长期记忆未启用。")
        try:
            result = await chat_handler.organize_memories_async(memory_scope)
        except MemoryStoreError:
            await matcher.finish(MEMORY_UNAVAILABLE_TEXT)
        mode = str(result.get("mode", "local"))
        mode_text = "AI" if mode == "ai" else "本地规则"
        if mode == "none":
            await matcher.finish(f"当前长期记忆较少，无需整理；保留 {result['kept']} 条。")
        await matcher.finish(
            f"已用{mode_text}整理长期记忆：保留 {result['kept']} 条，合并/移除 {result['removed']} 条。"
        )

    memory_content = _parse_remember_command(command)
    if memory_content is not None:
        if not chat_handler.memory_enabled():
            await matcher.finish("AI 长期记忆未启用。")
        if not memory_content:
            await matcher.finish("请在 .ai 记住 后面写要保存的内容。")
        try:
            item = await chat_handler.remember_async(memory_scope, memory_content)
        except MemoryStoreError:
            await matcher.finish(MEMORY_UNAVAILABLE_TEXT)
        if item is None:
            await matcher.finish("这条记忆是空的，没有保存。")
        await matcher.finish(f"已记住：{item['content']}")

    forget_target = _parse_forget_command(command)
    if forget_target is not None:
        if not chat_handler.memory_enabled():
            await matcher.finish("AI 长期记忆未启用。")
        if not forget_target:
            await matcher.finish("请指定要忘记的记忆编号，或使用 .ai 忘记 全部。")
        if forget_target in {"全部", "all"}:
            try:
                count = await chat_handler.clear_memories_async(memory_scope)
            except MemoryStoreError:
                await matcher.finish(MEMORY_UNAVAILABLE_TEXT)
            await matcher.finish(f"已清空 {count} 条长期记忆。")
        if not forget_target.isdigit():
            await matcher.finish("记忆编号应为数字，或使用 .ai 忘记 全部。")
        try:
            forgotten = await chat_handler.forget_async(memory_scope, forget_target)
        except MemoryStoreError:
            await matcher.finish(MEMORY_UNAVAILABLE_TEXT)
        if forgotten:
            await matcher.finish(f"已忘记第 {forget_target} 条长期记忆。")
        await matcher.finish(f"没有找到编号为 {forget_target} 的长期记忆。")

    if command in {"重载", "reload"}:
        try:
            role_store.reload()
        except Exception as exc:
            logger.exception("AI role preset reload failed: {}", exc)
            await matcher.finish("AI 角色预设重载失败，请检查角色配置文件。")
        selected_roles.pop(scope, None)
        chat_handler.clear_history()
        await matcher.finish("AI 角色预设已重载，当前会话角色已恢复为默认角色。")

    if command in {"重置", "reset", "清空"}:
        chat_handler.clear_history(_session_id(event, default_role))
        await matcher.finish("当前 AI 聊天上下文已清空。")

    if not role_store.has_role(command):
        await matcher.finish(f"没有找到角色：{command}\n可用角色：{'、'.join(role_store.list_roles())}")

    selected_roles[scope] = command
    chat_handler.clear_history(_session_id(event, default_role))
    await matcher.finish(f"已切换 AI 聊天角色：{command}")


@ai_chat.handle()
async def handle_ai_chat(bot: Bot, event: MessageEvent) -> None:
    default_role = await _default_role(event)
    role_name = _current_role(_conversation_scope(event), default_role)
    prompt, image_urls = _extract_chat_content(event.get_message(), bot)
    reply_context, reply_image_urls = _extract_reply_context(event.reply, bot)
    prompt = prompt or "你好"
    prompt = _build_prompt_with_reply(prompt, reply_context)
    response = await chat_handler.ask(
        prompt,
        _session_id(event, default_role),
        role_name,
        [*reply_image_urls, *image_urls],
        _memory_scope(event),
        web_search=await _web_search_enabled(event),
    )
    await ai_chat.finish(MessageSegment.text(response), at_sender=True)
