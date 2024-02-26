from nonebot.adapters import Message, Event
from nonebot.plugin import on_notice, on_request, on_message, on_command
from nonebot.adapters.onebot.v11 import Bot
import datetime

from nonebot import require, get_bot

noticeHandler = on_notice(block=False)
requestsHandler = on_request(block=False)
# messageHandler = on_message(block=False)
test_function_handler = on_command('test')


@test_function_handler.handle()
async def _():
    bot = get_bot()
    group_list = await bot.call_api('get_group_list')
    print(group_list)


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

# @messageHandler.handle()
# async def handle_messageHandler(bot: Bot, event: Event):
#     print("==========on_message==========")
#     print(
#         f"{datetime.datetime.fromtimestamp(event.dict()['time']).strftime('%Y-%m-%d %H:%M:%S')} "
#         f"{event.dict()['sender']['nickname']}: {event.dict()['message']}")
#     print("==============================")
