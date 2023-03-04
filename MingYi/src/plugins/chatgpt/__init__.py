import os
import re
from .dataSource import ChatHandler
import voiceHandler
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command, on_regex
from nonebot.adapters.onebot.v11 import MessageSegment, Bot

chatHandler = ChatHandler()
is_voice_answer = False
is_chatgpt_function_on = True
chat_mode = "默认"

chatgptMessageHandler = on_command("", to_me(), priority=100)
voice_answer_on = on_command("开启语音回复", to_me())
voice_answer_off = on_command("关闭语音回复", to_me())
chatgpt_function_on = on_command("开启聊天机器人", to_me(), permission=SUPERUSER)
chatgpt_function_off = on_command("关闭聊天机器人", to_me(), permission=SUPERUSER)
chatgpt_mode_change = on_regex("^切换到.+模式$", rule=to_me(), permission=SUPERUSER)


@chatgpt_mode_change.handle()
async def handle_chatgpt_mode_change(event: Event):
    global chat_mode
    message = event.dict()['message']
    chat_mode = re.findall(r"切换到(.+?)模式", str(message))[0]
    await chatgpt_mode_change.send(f"已切换到{chat_mode}模式")


@chatgptMessageHandler.handle()
async def handle_chatgptMessage(bot: Bot, event: Event, message: Message = CommandArg()):
    global chat_mode
    global is_chatgpt_function_on
    global is_voice_answer
    if not is_chatgpt_function_on:
        await chatgptMessageHandler.send("聊天功能已暂时被主人关闭")
        return
    if event.dict()['sender']['user_id'] == 1306401441 \
            or event.dict()['sender']['user_id'] == 1446534506 \
            or event.dict()['sender']['user_id'] == 2796338486:
        return
    chatResultMessage = chatHandler.ask(str(message), chat_mode, event.dict()['sender']['user_id'])
    # 语音回复部分
    if is_voice_answer:
        ssml = voiceHandler.message_to_ssml(chatResultMessage, voice_type="cheerful")
        waveUrl = voiceHandler.get_speech(ssml)
        await chatgptMessageHandler.send(MessageSegment.record("file:///" + str(waveUrl).replace('\\', '/')))
        os.remove(str(waveUrl))
    # 文字回复部分
    group_id = event.dict()['group_id'] if event.dict()['message_type'] == "group" else None
    cq_message = f"[CQ:reply,id={event.dict()['message_id']}][CQ:at,qq={event.dict()['sender']['user_id']}] " \
                 f"[CQ:at,qq={event.dict()['sender']['user_id']}]" \
        if group_id is not None else ""
    await bot.call_api("send_msg", message_type=f"{event.dict()['message_type']}",
                       user_id=event.dict()['sender']['user_id'],
                       group_id=group_id,
                       message=f"{cq_message}" + "\n" if group_id is not None else "" + f"{chatResultMessage}")


# @chatgptMessageHandler.handle()
# async def handle_chatgptMessage(bot: Bot, event: Event, message: Message = CommandArg()):
#     global is_chatgpt_function_on
#     if not is_chatgpt_function_on:
#         await chatgptMessageHandler.send("聊天功能已暂时被主人关闭")
#         return
#     if event.dict()['sender']['user_id'] == 1306401441 \
#             or event.dict()['sender']['user_id'] == 1446534506 \
#             or event.dict()['sender']['user_id'] == 2796338486:
#         return
#     chatResultMessage = dataSource.get_answer_from_web(message)
#     # 语音回复部分
#     if is_voice_answer:
#         ssml = voiceHandler.message_to_ssml(chatResultMessage, voice_type="cheerful")
#         waveUrl = voiceHandler.get_speech(ssml)
#         await chatgptMessageHandler.send(MessageSegment.record("file:///" + str(waveUrl).replace('\\', '/')))
#         os.remove(str(waveUrl))
#     # 文字回复部分
#     group_id = event.dict()['group_id'] if event.dict()['message_type'] == "group" else None
#     cq_message = f"[CQ:reply,id={event.dict()['message_id']}][CQ:at,qq={event.dict()['sender']['user_id']}] " \
#                  f"[CQ:at,qq={event.dict()['sender']['user_id']}]" \
#         if group_id is not None else ""
#     await bot.call_api("send_msg", message_type=f"{event.dict()['message_type']}",
#                        user_id=event.dict()['sender']['user_id'],
#                        group_id=group_id,
#                        message=f"{cq_message} \n{chatResultMessage}")


@voice_answer_on.handle()
async def handle_voice_answer_on(bot: Bot, event: Event):
    global is_voice_answer
    if await SUPERUSER(bot, event):
        is_voice_answer = True
        await voice_answer_on.send("语音回复已开启")
    else:
        await voice_answer_on.send("你没有权限开启语音回复", at_sender=True)


@voice_answer_off.handle()
async def handle_voice_answer_off(bot: Bot, event: Event):
    global is_voice_answer
    if await SUPERUSER(bot, event):
        is_voice_answer = False
        await voice_answer_off.send("语音回复已关闭")
    else:
        await voice_answer_off.send("你没有权限关闭语音回复", at_sender=True)


@chatgpt_function_on.handle()
async def handle_chatgpt_function_on(bot: Bot, event: Event):
    global is_chatgpt_function_on
    if await SUPERUSER(bot, event):
        is_chatgpt_function_on = True
        await chatgpt_function_on.send("聊天机器人已开启")
    else:
        await chatgpt_function_on.send("你没有权限开启聊天机器人", at_sender=True)


@chatgpt_function_off.handle()
async def handle_chatgpt_function_off(bot: Bot, event: Event):
    global is_chatgpt_function_on
    if await SUPERUSER(bot, event):
        is_chatgpt_function_on = False
        await chatgpt_function_off.send("聊天机器人已关闭")
    else:
        await chatgpt_function_off.send("你没有权限关闭聊天机器人", at_sender=True)
