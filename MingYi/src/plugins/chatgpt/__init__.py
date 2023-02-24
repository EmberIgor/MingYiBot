from nonebot.rule import to_me
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command, on_message
from revChatGPT.V1 import Chatbot

chatbot = Chatbot(config={
    "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ik1UaEVOVUpHTkVNMVFURTRNMEZCTWpkQ05UZzVNRFUxUlRVd1FVSkRNRU13UmtGRVFrRXpSZyJ9.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL3Byb2ZpbGUiOnsiZW1haWwiOiJ0YXJnYXJ5ZW5pZ29yQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJnZW9pcF9jb3VudHJ5IjoiSlAifSwiaHR0cHM6Ly9hcGkub3BlbmFpLmNvbS9hdXRoIjp7InVzZXJfaWQiOiJ1c2VyLXpieW9NWFh3SWNJUzFHNmNnbUIwZVFkeiJ9LCJpc3MiOiJodHRwczovL2F1dGgwLm9wZW5haS5jb20vIiwic3ViIjoiZ29vZ2xlLW9hdXRoMnwxMTUxNTQ2MDExNzU2ODU5MTc0MTIiLCJhdWQiOlsiaHR0cHM6Ly9hcGkub3BlbmFpLmNvbS92MSIsImh0dHBzOi8vb3BlbmFpLm9wZW5haS5hdXRoMGFwcC5jb20vdXNlcmluZm8iXSwiaWF0IjoxNjc3MTE4MTM5LCJleHAiOjE2NzgzMjc3MzksImF6cCI6IlRkSkljYmUxNldvVEh0Tjk1bnl5d2g1RTR5T282SXRHIiwic2NvcGUiOiJvcGVuaWQgcHJvZmlsZSBlbWFpbCBtb2RlbC5yZWFkIG1vZGVsLnJlcXVlc3Qgb3JnYW5pemF0aW9uLnJlYWQgb2ZmbGluZV9hY2Nlc3MifQ.w_O4DkdMq6M4EKExWn-g-AHWf_3Ab-5Znl0UPhokfFXRQ1Bji1W514JOlSH_UGPhinCa23Nxb9pFjj5kpdox0ssmiMk2FlnjNgL8zdIBH0L3yFkahVYIJZDoP1JMyrRwxqLuQDRu1p08pISC48j2CDQfTl0ECy8DMfPFTu9Bk2ZwhmSBLiNd4pvLFWRAuoa-fJGqdcFxFxmkfoEXCzGL8kCQmveapiBZGXkAdBY--QpRxYn8F_RzRwKn98o1jw25aqbRMDEfpITlwP-HzBeavHoEkOIjhC4gTq-GDW2oJ61UjpQLIwCuzoaDGszj6N3nnBX4jO-yMzeaxoStAEJbdA"
})
chatgptMessageHandler = on_command("", to_me())

isWaitingForRes = False


@chatgptMessageHandler.handle()
async def handle_chatgptMessage(event: Event, message: Message = CommandArg()):
    global chatbot
    global isWaitingForRes
    if isWaitingForRes:
        await chatgptMessageHandler.send(message="正在回复其他消息，请稍后再试", at_sender=True)
        return
    isWaitingForRes = True
    conversation = None
    chatResultMessage = ""
    conversationList = chatbot.get_conversations()
    if len(conversationList) > 0:
        conversation = conversationList[0]['id']
    for data in chatbot.ask(str(message), conversation_id=str(conversation) if conversation else None):
        chatResultMessage = data["message"]
    await chatgptMessageHandler.send(message=chatResultMessage, at_sender=True)
    isWaitingForRes = False
