import os
# import voiceHandler
import re
from nonebot import on_regex, on_command
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.rule import to_me
from nonebot.adapters import Event
from nonebot.typing import T_State
from .dataSource import *

dice_order_pattern = r"\.?r\d*d\d+(?:/\d+)?"
dice_player = on_regex(dice_order_pattern)


@dice_player.handle()
async def _(event: Event, state: T_State):
    print("匹配到了")
    print(event.dict()['message'])
    rolls, sides, threshold = dataSource.extract_dice_data(str(event.dict()['message']))
    dice_results, total, effect = dataSource.roll_dice(rolls, sides, threshold)
    chat_api_res_message = dataSource.chat(rolls, dice_results, total, effect)
    await dice_player.send(chat_api_res_message, at_sender=True)
