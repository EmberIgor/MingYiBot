import os
import re
from .dataSource import *
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command, on_regex
from nonebot.adapters.onebot.v11 import MessageSegment, Bot

query_subscription_link = on_command("订阅链接")
apply_for_a_subscription_link = on_command("申请订阅链接")


@query_subscription_link.handle()
async def handle_query_subscription_link(bot: Bot, event: Event, message: Message = CommandArg()):
    user_id = event.dict()['sender']['user_id']
    subscription_link = get_subscription_link(user_id)
    if subscription_link["status"] == "error":
        await query_subscription_link.send(subscription_link["message"])
    if subscription_link["subscription_link"] is None:
        await query_subscription_link.send(f"您还没有申请订阅链接，请发送“申请订阅链接”申请", at_sender=True)
    else:
        # 如果是群消息
        if event.dict()['message_type'] == "group":
            await query_subscription_link.send(f"您的订阅链接已经私聊给您", at_sender=True)
        await bot.call_api("send_msg", message_type=f"private", user_id=event.dict()['sender']['user_id'],
                           message=f"您的订阅链接为：\n{subscription_link['subscription_link']}")


@apply_for_a_subscription_link.handle()
async def handle_apply_for_a_subscription_link(bot: Bot, event: Event, message: Message = CommandArg()):
    await apply_for_a_subscription_link.send(f"正在申请订阅链接，请稍等", at_sender=True)
    user_id = event.dict()['sender']['user_id']
    apply_link = apply_subscription_link(user_id, event.dict()['sender']['nickname'])
    if apply_link["status"] == "error":
        await apply_for_a_subscription_link.send(apply_link["message"])
    else:
        if event.dict()['message_type'] == "group":
            await apply_for_a_subscription_link.send(f"您的订阅链接已经私聊给您", at_sender=True)
        await bot.call_api("send_msg", message_type=f"private", user_id=event.dict()['sender']['user_id'],
                           message=f"您的订阅链接为：\n{apply_link['subscription_link']}")
