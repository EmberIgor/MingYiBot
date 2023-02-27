import datetime
from nonebot import on_regex, on_command
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.rule import to_me
from nonebot.adapters import Event
from nonebot.typing import T_State
from .data_source import *
import re
import os

pattern = "(^愤怒|^镇静|^开朗|^不满|^惊恐|^温柔|^抒情|^一般|^助理|^聊天|^客户服务|^播音|^悲伤|^严肃)的说*"
SPEECH = on_regex(pattern)
SAY = on_command("说", rule=to_me())


@SPEECH.handle()
async def _(event: Event, state: T_State):
    print(re.split("的说", str(event.dict()['message']), 1))

    state["voice"] = re.split("的说", str(event.dict()['message']), 1)
    state["voice"][0] = data_source.voiceList.get(state["voice"][0])
    now = datetime.datetime.now()
    waveName = str(now.year) + str(now.month) + str(now.day) + str(now.hour) + str(now.minute) + str(
        now.second) + ".wav"
    await get_YuYing(state["voice"][1], waveName, state["voice"][0])
    await SPEECH.send(
        MessageSegment.record(
            "file:///" + str(os.path.dirname(os.path.abspath(__file__))).replace('\\', '/') + "/" + waveName))
    os.remove(str(os.path.dirname(os.path.abspath(__file__))) + "/" + waveName)


@SAY.handle()
async def _(event: Event, state: T_State):
    state["voice"] = re.split("^(说)", str(event.dict()['message']))
    now = datetime.datetime.now()
    waveName = str(now.year) + str(now.month) + str(now.day) + str(now.hour) + str(now.minute) + str(
        now.second) + ".wav"
    await get_YuYing(state["voice"][2], waveName, "chat")
    await SAY.send(
        MessageSegment.record(
            "file:///" + str(os.path.dirname(os.path.abspath(__file__))).replace('\\', '/') + "/" + waveName))
    os.remove(str(os.path.dirname(os.path.abspath(__file__))) + "/" + waveName)
