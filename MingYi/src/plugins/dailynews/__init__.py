import requests
import json
import aiohttp
import asyncio
import datetime
from nonebot import require, get_bot
from nonebot.plugin import on_command
from nonebot.adapters.onebot.v11 import MessageSegment

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

dailyNews = on_command("今日新闻", block=True)


@dailyNews.handle()
async def handle_dailyNews():
    res = requests.get("http://dwz.2xb.cn/zaob")
    url = json.loads(res.text)["imageUrl"]
    await dailyNews.send(MessageSegment.image(url))


@scheduler.scheduled_job('cron', hour='8', minute='00')
async def _():
    bot = get_bot()
    group_list = await bot.call_api('get_group_list')
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get("http://dwz.2xb.cn/zaob") as res:
                news_info = json.loads(await res.text())
                datatime = datetime.datetime.strptime(news_info["datatime"], "%Y-%m-%d").date()
                current_date = datetime.date.today()
                if datatime == current_date:
                    break
            await asyncio.sleep(60)  # 使用异步sleep
    url = news_info["imageUrl"]
    for group in group_list:
        # 如果群号不在黑名单中 984625860, 1041873822
        if group["group_id"] not in [984625860, 1041873822]:
            await bot.call_api('send_group_msg', group_id=group["group_id"], message=f'[CQ:image,file={url}]')
