from nonebot import get_driver
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.plugin import on_notice
from nonebot.rule import Rule
from .dataSource import *


def check_poke() -> Rule:
    async def _checker(event: Event) -> bool:
        if event.notice_type == 'notify':
            if event.sub_type == 'poke':
                return True
            else:
                return False
        else:
            return False

    return Rule(_checker)


def check_honor() -> Rule:
    async def _checker(event: Event) -> bool:
        if event.notice_type == 'notify':
            if event.sub_type == 'honor':
                return True
            else:
                return False
        else:
            return False

    return Rule(_checker)


cuoyicuo = on_notice(rule=check_poke())
honorHandler = on_notice(rule=check_honor())


@cuoyicuo.handle()
async def handle_cuoyicuo(event: Event):
    eventDict = event.dict()
    if eventDict['target_id'] == get_driver().config.self_id:
        res = await getYiYan()
        await cuoyicuo.send(res['hitokoto'])
    else:
        await cuoyicuo.send(MessageSegment.at(str(eventDict['target_id'])) + '看起来有人找您')


@honorHandler.handle()
async def handle_honorHandler(event: Event):
    eventDict = event.dict()
    if eventDict['honor_type'] == "talkative":
        print("龙王")
