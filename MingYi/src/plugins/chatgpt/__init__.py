import os
import dataSource
import voiceHandler
import openai
from nonebot import get_driver
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command
from revChatGPT.V1 import Chatbot
from nonebot.adapters.onebot.v11 import MessageSegment, Bot

chatbot = Chatbot(config={
    "access_token": get_driver().config.chatgpt_access_token
})
conversationList = chatbot.get_conversations()
is_voice_answer = False
is_chatgpt_function_on = True

chatgptMessageHandler = on_command("", to_me(), priority=100)
voice_answer_on = on_command("开启语音回复", to_me())
voice_answer_off = on_command("关闭语音回复", to_me())
chatgpt_function_on = on_command("开启聊天机器人", to_me(), permission=SUPERUSER)
chatgpt_function_off = on_command("关闭聊天机器人", to_me(), permission=SUPERUSER)


@chatgptMessageHandler.handle()
async def handle_chatgptMessage(bot: Bot, event: Event, message: Message = CommandArg()):
    global is_chatgpt_function_on
    if not is_chatgpt_function_on:
        await chatgptMessageHandler.send("聊天功能已暂时被主人关闭")
        return
    if event.dict()['sender']['user_id'] == 1306401441 \
            or event.dict()['sender']['user_id'] == 1446534506 \
            or event.dict()['sender']['user_id'] == 2796338486:
        return
    global chatbot
    global conversationList
    conversation = None
    chatResultMessage = ""
    character_settings = "假设你是一个叫茗懿的中国女生，用活泼可爱的语气说话。"
    send_message = character_settings + str(message)
    if len(conversationList) > 0:
        conversation = conversationList[0]['id']
    print(conversation)
    if conversation is None:
        for data in chatbot.ask(send_message):
            chatResultMessage = data["message"]
    else:
        try:
            print(f"使用对话id: {conversation}")
            for data in chatbot.ask(send_message, conversation_id=str(conversation)):
                chatResultMessage = data["message"]
        except KeyError:
            for data in chatbot.ask(send_message):
                chatResultMessage = data["message"]
            conversationList = chatbot.get_conversations()
    if is_voice_answer:
        ssml = voiceHandler.message_to_ssml(chatResultMessage, voice_type="cheerful")
        waveUrl = voiceHandler.get_speech(ssml)
        await chatgptMessageHandler.send(MessageSegment.record("file:///" + str(waveUrl).replace('\\', '/')))
        os.remove(str(waveUrl))
    # else:
    #     # await chatgptMessageHandler.send(message=chatResultMessage, at_sender=True)
    #     group_id = event.dict()['group_id'] if event.dict()['message_type'] == "group" else None
    #     cq_message = f"[CQ:reply,id={event.dict()['message_id']}][CQ:at,qq={event.dict()['sender']['user_id']}] " \
    #                  f"[CQ:at,qq={event.dict()['sender']['user_id']}]" \
    #         if group_id is not None else ""
    #     await bot.call_api("send_msg", message_type=f"{event.dict()['message_type']}",
    #                        user_id=event.dict()['sender']['user_id'],
    #                        group_id=group_id,
    #                        message=f"{cq_message} {chatResultMessage}")
    group_id = event.dict()['group_id'] if event.dict()['message_type'] == "group" else None
    cq_message = f"[CQ:reply,id={event.dict()['message_id']}][CQ:at,qq={event.dict()['sender']['user_id']}] " \
                 f"[CQ:at,qq={event.dict()['sender']['user_id']}]" \
        if group_id is not None else ""
    await bot.call_api("send_msg", message_type=f"{event.dict()['message_type']}",
                       user_id=event.dict()['sender']['user_id'],
                       group_id=group_id,
                       message=f"{cq_message} \n{chatResultMessage}")


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
