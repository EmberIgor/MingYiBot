from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.rule import Rule


def message_mentions_bot(message: Message, bot: Bot) -> bool:
    bot_id = str(bot.self_id)
    return any(
        segment.type == "at" and str(segment.data.get("qq", "")) == bot_id
        for segment in message
    )


async def _is_directed_to_bot(bot: Bot, event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return True

    if bool(getattr(event, "to_me", False)):
        return True

    return message_mentions_bot(event.get_message(), bot)


def directed_to_bot() -> Rule:
    return Rule(_is_directed_to_bot)
