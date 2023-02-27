from nonebot import get_driver
from nonebot.rule import to_me
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command
from revChatGPT.V1 import Chatbot

chatbot = Chatbot(config={
    "access_token": get_driver().config.chatgpt_access_token
})
chatgptMessageHandler = on_command("", to_me(), priority=100)


@chatgptMessageHandler.handle()
async def handle_chatgptMessage(event: Event, message: Message = CommandArg()):
    global chatbot
    conversation = None
    chatResultMessage = ""
    conversationList = chatbot.get_conversations()
    character_settings = "接下来你将扮演一个叫茗懿的中国女生，用活泼可爱的语气说话。接下来是我对你说的话："
    send_message = character_settings + str(message)
    if len(conversationList) > 0:
        conversation = conversationList[0]['id']
    if conversation is None:
        for data in chatbot.ask(send_message):
            chatResultMessage = data["message"]
    else:
        for data in chatbot.ask(send_message, conversation_id=str(conversation)):
            chatResultMessage = data["message"]
    await chatgptMessageHandler.send(message=chatResultMessage, at_sender=True)
