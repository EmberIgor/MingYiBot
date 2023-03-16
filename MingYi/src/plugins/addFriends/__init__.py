from nonebot import get_bot
from nonebot.adapters import Event
from nonebot.plugin import on_request
from nonebot.rule import Rule


def add_friend_checker() -> Rule:
    async def _checker(event: Event) -> bool:
        if event.dict()['request_type'] == 'group' or event.dict()['request_type'] == 'friend':
            return True
        else:
            return False

    return Rule(_checker)


requestsHandler = on_request(rule=add_friend_checker())


@requestsHandler.handle()
async def handle_requests_handler(event: Event):
    event_dict = event.dict()
    # 如果是好友请求
    if event_dict['request_type'] == 'friend':
        # 检查暗号
        if event_dict['comment'] == 'fire-keeper':
            await get_bot().call_api('set_friend_add_request', flag=event_dict['flag'], approve=True)
        else:
            await get_bot().call_api('set_friend_add_request', flag=event_dict['flag'], approve=False,
                                     reason='暗号错误')
