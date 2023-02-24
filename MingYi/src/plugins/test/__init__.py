from nonebot.rule import to_me
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_notice, on_request

noticeHandler = on_notice()
requestsHandler = on_request()


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
