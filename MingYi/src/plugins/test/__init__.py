from nonebot.adapters import Event
from nonebot.plugin import on_notice, on_request, on_message

noticeHandler = on_notice(block=False)
requestsHandler = on_request(block=False)
messageHandler = on_message(block=False)


@noticeHandler.handle()
async def handle_notice_handler(event: Event):
    print("==========on_notice==========")
    print(event.dict())
    print("=============================")


@requestsHandler.handle()
async def handle_requests_handler(event: Event):
    print("==========on_request==========")
    print(event.dict())
    print("==============================")


@messageHandler.handle()
async def handle_message_handler(event: Event):
    print("==========on_message==========")
    print(event.dict())
    print("==============================")
