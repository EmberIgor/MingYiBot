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
conversationList = chatbot.get_conversations()


@chatgptMessageHandler.handle()
async def handle_chatgptMessage(event: Event, message: Message = CommandArg()):
    if event.dict()['sender']['user_id'] == 1306401441:
        return
    global chatbot
    global conversationList
    conversation = None
    chatResultMessage = ""
    character_settings = "接下来你将扮演一个叫茗懿的中国女生，用活泼可爱的语气说话。接下来是我对你说的话："
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
        except KeyError as key_error:
            for data in chatbot.ask(send_message):
                chatResultMessage = data["message"]
            conversationList = chatbot.get_conversations()
    await chatgptMessageHandler.send(message=chatResultMessage, at_sender=True)
