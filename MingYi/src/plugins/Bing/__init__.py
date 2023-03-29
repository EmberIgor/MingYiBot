import os
import re
from .dataSource import BingHandler
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command, on_regex
from nonebot.adapters.onebot.v11 import MessageSegment, Bot

bing_bot = BingHandler()
bing_message_handler = on_command("bing,", aliases={"bing，"})


@bing_message_handler.handle()
async def handle_bing_message(bot: Bot, event: Event, message: Message = CommandArg()):
    bing_message_result = await bing_bot.ask(str(message), event.dict()['sender']['user_id'])
    if bing_message_result["is_error"]:
        await bing_message_handler.send(bing_message_result["message"], at_sender=True)
    else:
        if bing_message_result["is_bot_refreshed"]:
            await bing_message_handler.send(
                "因为您的对话数量（包括bot的回复）已经超过15次，或是距离上次对话已经超过10分钟，茗懿为你刷新了对话。",
                at_sender=True)
        await bing_message_handler.send(bing_message_result["message"], at_sender=True)
