import re

from nonebot import get_plugin_config, logger, on_command, on_message, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me

from .config import Config
from .data_source import ChatHandler
from .role_store import RoleStore

__plugin_meta__ = PluginMetadata(
    name="ai_chat",
    description="在机器人被 @ 且未命中其他命令时提供 AI 聊天兜底能力",
    usage="@机器人 聊天内容\n/ai角色 [角色名|列表|重载|重置]",
    config=Config,
)

config = get_plugin_config(Config)
role_store = RoleStore(config.aichat_roles_path, config.aichat_default_role)
chat_handler = ChatHandler(config, role_store)
selected_roles: dict[str, str] = {}

role_command = on_command("ai角色", aliases={"聊天角色", "角色"}, priority=20, block=True)
role_alias_command = on_regex(r"^(?:聊天角色|角色)(?:\s+|$)(.*)$", priority=20, block=True)
ai_chat = on_message(to_me(), priority=100, block=True)


def _extract_chat_text(message: Message, bot: Bot) -> str:
    parts: list[str] = []
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
            parts.append("[image]")
        else:
            parts.append(f"[{segment.type}]")

    return " ".join(parts).strip()


def _conversation_scope(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}:user:{event.user_id}"
    return f"private:user:{event.user_id}"


def _current_role(scope: str) -> str:
    role_name = selected_roles.get(scope, config.aichat_default_role)
    if role_store.has_role(role_name):
        return role_name
    return config.aichat_default_role


def _session_id(event: MessageEvent) -> str:
    scope = _conversation_scope(event)
    return f"{scope}:role:{_current_role(scope)}"


@role_command.handle()
async def handle_role_command(event: MessageEvent, args: Message = CommandArg()) -> None:
    await _handle_role_command(event, args.extract_plain_text().strip(), role_command)


@role_alias_command.handle()
async def handle_role_alias_command(event: MessageEvent) -> None:
    command = re.sub(r"^(?:聊天角色|角色)(?:\s+|$)", "", event.get_plaintext(), count=1).strip()
    await _handle_role_command(event, command, role_alias_command)


async def _handle_role_command(event: MessageEvent, command: str, matcher) -> None:
    chat_handler.cleanup_expired()

    scope = _conversation_scope(event)

    if not command or command in {"列表", "list"}:
        current = _current_role(scope)
        roles = "、".join(role_store.list_roles())
        await matcher.finish(f"当前角色：{current}\n可用角色：{roles}")

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
        chat_handler.clear_history(_session_id(event))
        await matcher.finish("当前 AI 聊天上下文已清空。")

    if not role_store.has_role(command):
        await matcher.finish(f"没有找到角色：{command}\n可用角色：{'、'.join(role_store.list_roles())}")

    selected_roles[scope] = command
    chat_handler.clear_history(_session_id(event))
    await matcher.finish(f"已切换 AI 聊天角色：{command}")


@ai_chat.handle()
async def handle_ai_chat(bot: Bot, event: MessageEvent) -> None:
    prompt = _extract_chat_text(event.get_message(), bot) or "你好"
    response = await chat_handler.ask(prompt, _session_id(event), _current_role(_conversation_scope(event)))
    await ai_chat.finish(MessageSegment.text(response), at_sender=True)
