import requests
import json
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command
from nonebot.adapters.onebot.v11 import MessageSegment

dailyNews = on_command("今日新闻", block=True)


@dailyNews.handle()
async def handle_dailyNews(event: Event, message: Message = CommandArg()):
    res = requests.get("https://api.vvhan.com/api/60s?type=json")
    url = json.loads(res.text)["imgUrl"]
    await dailyNews.send(MessageSegment.image(url))

# test
