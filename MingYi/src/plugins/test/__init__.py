from nonebot.adapters import Message, Event
from nonebot.plugin import on_notice, on_request, on_message

noticeHandler = on_notice()
requestsHandler = on_request()
messageHandler = on_message()


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
async def handle_messageHandler(event: Event):
    print("==========on_message==========")
    print(event.dict())
    print(event.dict()['sender']['user_id'])
    print("==============================")
