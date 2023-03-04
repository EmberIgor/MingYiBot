import requests
import json
from nonebot import require, get_bot
from nonebot.plugin import on_command
from nonebot.adapters.onebot.v11 import MessageSegment
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

dailyNews = on_command("今日新闻", block=True)


@dailyNews.handle()
async def handle_dailyNews():
    res = requests.get("https://api.vvhan.com/api/60s?type=json")
    url = json.loads(res.text)["imgUrl"]
    await dailyNews.send(MessageSegment.image(url))


@scheduler.scheduled_job('cron', hour='08', minute='00')
async def _():
    bot = get_bot()
    group_list = await bot.call_api('get_group_list')
    res = requests.get("https://api.vvhan.com/api/60s?type=json")
    url = json.loads(res.text)["imgUrl"]
    for group in group_list:
        await bot.call_api('send_group_msg', group_id=group["group_id"], message=f'[CQ:image,file={url}]')
