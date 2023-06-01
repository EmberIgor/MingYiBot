from nonebot.adapters import Message, Event
from nonebot.plugin import on_notice, on_request, on_message
from nonebot.adapters.onebot.v11 import Bot
import datetime

noticeHandler = on_notice(block=False)
requestsHandler = on_request(block=False)
messageHandler = on_message(block=False)


@noticeHandler.handle()
async def handle_noticeHandler(event: Event):
    print("==========on_notice==========")
    print(event.dict())
    print("=============================")


@requestsHandler.handle()
async def handle_requestsHandler(event: Event):
    print("==========on_request==========")
    print(event.dict())
    print("==============================")


@messageHandler.handle()
async def handle_messageHandler(bot: Bot, event: Event):
    print("==========on_message==========")
    print(event.dict())
    print(
        f"{datetime.datetime.fromtimestamp(event.dict()['time']).strftime('%Y-%m-%d %H:%M:%S')} "
        f"{event.dict()['sender']['nickname']}: {event.dict()['message']}")
    print("==============================")
