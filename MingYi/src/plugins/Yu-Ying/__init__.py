import os
import voiceHandler
import re
from nonebot import on_regex, on_command
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.rule import to_me
from nonebot.adapters import Event
from nonebot.typing import T_State

pattern = "(^愤怒|^平静|^开朗|^不满|^惊恐|^温柔|^抒情|^一般|^助理|^聊天|^客户服务|^播音|^悲伤|^严肃|^撒娇|^阅读|^默认)的说*"
SPEECH = on_regex(pattern)
SAY = on_command("说", rule=to_me())


@SPEECH.handle()
async def _(event: Event, state: T_State):
    state["voice"] = re.split("的说", str(event.dict()['message']), 1)
    state["voice"][0] = voiceHandler.voiceList[state["voice"][0]]
    ssml = voiceHandler.message_to_ssml(state["voice"][1], voice_type=state["voice"][0])
    waveUrl = voiceHandler.get_speech(ssml)
    await SPEECH.send(MessageSegment.record("file:///" + str(waveUrl).replace('\\', '/')))
    os.remove(str(waveUrl))


@SAY.handle()
async def _(event: Event, state: T_State):
    state["voice"] = re.split("^(说)", str(event.dict()['message']))
    ssml = voiceHandler.message_to_ssml(state["voice"][2], voice_type="cheerful")
    waveUrl = voiceHandler.get_speech(ssml)
    await SAY.send(MessageSegment.record("file:///" + str(waveUrl).replace('\\', '/')))
    os.remove(str(waveUrl))
