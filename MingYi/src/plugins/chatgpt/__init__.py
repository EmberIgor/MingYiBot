from nonebot import get_driver
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command
from revChatGPT.V1 import Chatbot
from nonebot.adapters.onebot.v11 import MessageSegment, Bot
import voiceHandler
import os

chatbot = Chatbot(config={
    "access_token": get_driver().config.chatgpt_access_token
})
conversationList = chatbot.get_conversations()
is_voice_answer = False

chatgptMessageHandler = on_command("", to_me(), priority=100)
voice_answer_on = on_command("开启语音回复", to_me())
voice_answer_off = on_command("关闭语音回复", to_me())


@chatgptMessageHandler.handle()
async def handle_chatgptMessage(event: Event, message: Message = CommandArg()):
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
    if conversation is None:
        for data in chatbot.ask(send_message):
            chatResultMessage = data["message"]
    else:
        try:
            for data in chatbot.ask(send_message, conversation_id=str(conversation)):
                chatResultMessage = data["message"]
        except KeyError:
            for data in chatbot.ask(send_message):
                chatResultMessage = data["message"]
            conversationList = chatbot.get_conversations()
    # await chatgptMessageHandler.send(message=chatResultMessage, at_sender=True)
    if is_voice_answer:
        ssml = voiceHandler.message_to_ssml(chatResultMessage, voice_type="cheerful")
        waveUrl = voiceHandler.get_speech(ssml)
        await chatgptMessageHandler.send(MessageSegment.record("file:///" + str(waveUrl).replace('\\', '/')))
        os.remove(str(waveUrl))
    else:
        await chatgptMessageHandler.send(message=chatResultMessage, at_sender=True)


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
