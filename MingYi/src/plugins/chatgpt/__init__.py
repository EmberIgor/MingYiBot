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
is_debug_mode_on = False
chat_mode = "默认"

chatgptMessageHandler = on_command("", to_me(), priority=100)
voice_answer_switch = on_regex("^(^开启|^关闭)语音回复$", permission=SUPERUSER)
chatgpt_function_switch = on_regex("^(^开启|^关闭)聊天机器人$", permission=SUPERUSER)
debug_mode_switch = on_regex("^(^开启|^关闭)调试模式$", rule=to_me(), permission=SUPERUSER)
chatgpt_mode_change = on_regex("^切换到.+模式$", rule=to_me())
clean_chat_data = on_command("重置会话", rule=to_me())
clean_chat_data_all = on_command("重置所有会话", rule=to_me(), permission=SUPERUSER)


@chatgptMessageHandler.handle()
async def handle_chatgpt_message(bot: Bot, event: Event, message: Message = CommandArg()):
    global chat_mode
    global is_chatgpt_function_on
    global is_voice_answer
    if not is_chatgpt_function_on:
        await chatgptMessageHandler.send("聊天功能已暂时被主人关闭")
        return
    if is_debug_mode_on:
        if not await SUPERUSER(bot, event):
            await chatgptMessageHandler.send("目前主人设定为调试模式，您无法使用聊天功能", at_sender=True)
            return
    if event.dict()['sender']['user_id'] == 1446534506 or event.dict()['sender']['user_id'] == 2796338486:
        return
    # 当前会话将会消耗的令牌次数
    token_cost = chatHandler.num_tokens_from_messages(str(message), chat_mode, event.dict()['sender']['user_id'])
    print(f"当前会话将会消耗的令牌次数为{token_cost}")
    if 4090 > token_cost > 3000:
        await chatgptMessageHandler.send(
            f"您的会话记录长度已经累计达到{token_cost}的长度，茗懿将继续与您的对话，但为了减轻茗懿的负担，如无必要继续记忆会话，请使用`重置会话`指令重置您与茗懿在当前模式的对话")
    elif token_cost > 4090:
        chatHandler.clean_conversations(chat_mode, event.dict()['sender']['user_id'])
        await chatgptMessageHandler.send(f"您的会话记录长度已经超过4090个token,您与茗懿在当前模式下的会话已被重置。")
    chat_result_message = chatHandler.ask(str(message), chat_mode, event.dict()['sender']['user_id'])
    # 语音回复部分
    if is_voice_answer:
        ssml = voiceHandler.message_to_ssml(chat_result_message, voice_type="cheerful")
        wave_url = voiceHandler.get_speech(ssml)
        await chatgptMessageHandler.send(MessageSegment.record("file:///" + str(wave_url).replace('\\', '/')))
        os.remove(str(wave_url))
    # 文字回复部分
    group_id = event.dict()['group_id'] if event.dict()['message_type'] == "group" else None
    cq_message = f"[CQ:reply,id={event.dict()['message_id']}][CQ:at,qq={event.dict()['sender']['user_id']}] " \
                 f"[CQ:at,qq={event.dict()['sender']['user_id']}]" \
        if group_id is not None else ""
    linefeed = "\n" if group_id is not None else ""
    await bot.call_api("send_msg", message_type=f"{event.dict()['message_type']}",
                       user_id=event.dict()['sender']['user_id'],
                       group_id=group_id,
                       message=f"{cq_message}" + linefeed + f"{chat_result_message}")


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

@chatgpt_mode_change.handle()
async def handle_chatgpt_mode_change(bot: Bot, event: Event):
    global chat_mode
    if await SUPERUSER(bot, event):
        message = event.dict()['message']
        chat_mode = re.findall(r"切换到(.+?)模式", str(message))[0]
        await chatgpt_mode_change.send(f"已切换到{chat_mode}模式")
    else:
        await chatgpt_mode_change.send("您没有权限执行此操作", at_sender=True)


@voice_answer_switch.handle()
async def handle_voice_answer_switch(bot: Bot, event: Event):
    global is_voice_answer
    if await SUPERUSER(bot, event):
        message = event.dict()['message']
        mode_choose = re.findall(r"(.+?)语音回复", str(message))[0]
        is_voice_answer = True if mode_choose == "开启" else False
        await voice_answer_switch.send(f"语音回复已{mode_choose}")
    else:
        await voice_answer_switch.send("你没有权限切换语音回复", at_sender=True)


@chatgpt_function_switch.handle()
async def handle_chatgpt_function_switch(bot: Bot, event: Event):
    global is_chatgpt_function_on
    if await SUPERUSER(bot, event):
        message = event.dict()['message']
        mode_choose = re.findall(r"(.+?)聊天机器人", str(message))[0]
        is_chatgpt_function_on = True if mode_choose == "开启" else False
        await chatgpt_function_switch.send(f"聊天功能已{'开启' if is_chatgpt_function_on else '关闭'}")
    else:
        await chatgpt_function_switch.send("你没有权限切换聊天机器人状态", at_sender=True)


@debug_mode_switch.handle()
async def handle_debug_mode_switch(bot: Bot, event: Event):
    global is_debug_mode_on
    message = event.dict()['message']
    mode_choose = re.findall(r"(.+?)调试模式", str(message))[0]
    if mode_choose == "开启":
        is_debug_mode_on = True
    elif mode_choose == "关闭":
        is_debug_mode_on = False
    if await SUPERUSER(bot, event):
        await debug_mode_switch.send(f"调试模式已{'开启' if is_debug_mode_on else '关闭'}")
    else:
        await debug_mode_switch.send("你没有权限开启调试模式", at_sender=True)


@clean_chat_data.handle()
async def handle_clean_chat_data(event: Event):
    global chat_mode
    user_id = event.dict()['sender']['user_id']
    if chatHandler.clean_conversations(chat_mode, user_id):
        await clean_chat_data.send(f"用户：{user_id}在{chat_mode}模式下的会话已重置", at_sender=True)
    else:
        await clean_chat_data.send(f"重置会话失败", at_sender=True)


@clean_chat_data_all.handle()
async def handle_clean_chat_data_all(bot: Bot, event: Event):
    global chat_mode
    if await SUPERUSER(bot, event):
        if chatHandler.clean_all_conversations():
            await clean_chat_data_all.send(f"所有会话已重置")
        else:
            await clean_chat_data_all.send(f"重置会话失败")
    else:
        await clean_chat_data_all.send("你没有权限重置所有会话", at_sender=True)
