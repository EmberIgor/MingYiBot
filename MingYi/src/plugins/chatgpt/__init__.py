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
    if len(conversationList) > 0:
        conversation = conversationList[0]['id']
    for data in chatbot.ask(str(message), conversation_id=str(conversation) if conversation else None):
        chatResultMessage = data["message"]
    await chatgptMessageHandler.send(message=chatResultMessage, at_sender=True)
