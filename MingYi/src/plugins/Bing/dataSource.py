import json
import datetime
from EdgeGPT import Chatbot, ConversationStyle
import re


class BingHandler:
    # 记录各个人对话的字典
    transcripts_of_conversations = {}

    def __init__(self):
        with open('./cookie.json', 'r') as f:
            self.cookies = json.load(f)

    async def ask(self, message: str, user_id: int):
        bing_res_message = "似乎出了一些问题，无法回复。"
        is_bot_refreshed = False
        is_error = False
        try:
            if user_id not in self.transcripts_of_conversations:
                self.transcripts_of_conversations[user_id] = {
                    "bot": Chatbot(cookies=self.cookies),
                    "invocationId": '0',
                    "last_conversation_time": datetime.datetime.now()
                }
            time_diff = datetime.datetime.now() - self.transcripts_of_conversations[user_id]["last_conversation_time"]
            if time_diff.total_seconds() > 600 or int(self.transcripts_of_conversations[user_id]["invocationId"]) >= 14:
                self.transcripts_of_conversations[user_id]["bot"].close()
                self.transcripts_of_conversations[user_id]["bot"] = Chatbot(cookies=self.cookies)
            bot_response = await self.transcripts_of_conversations[user_id]["bot"].ask(
                prompt=str(message),
                conversation_style=ConversationStyle.balanced
            )
            bing_res_message = re.sub(r'\[\^.+?\^]', r'', bot_response["item"]["messages"][1]["text"])
            self.transcripts_of_conversations[user_id]["invocationId"] = bot_response["invocationId"]
            self.transcripts_of_conversations[user_id]["last_conversation_time"] = datetime.datetime.now()
        except Exception as e:
            print(e)
            is_error = True
            bing_res_message = "似乎出了一些问题，已经重置会话，错误类型: " + str(type(e))
            self.transcripts_of_conversations[user_id]["bot"].close()
            del self.transcripts_of_conversations[user_id]
        return {
            "message": bing_res_message,
            "is_bot_refreshed": is_bot_refreshed,
            "is_error": is_error,
            "invocationId": self.transcripts_of_conversations[user_id]["invocationId"] if not is_error else None
        }
