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
    # res = requests.get("http://dwz.2xb.cn/zaob")
    # url = json.loads(res.text)["imageUrl"]
    url = "https://api.jun.la/60s.php?format=image"
    await dailyNews.send(MessageSegment.image(url))
    # await dailyNews.send(MessageSegment.image("http://dwz.2xb.cn/zaob"))


@scheduler.scheduled_job('cron', hour='09', minute='00')
async def _():
    bot = get_bot()
    group_list = await bot.call_api('get_group_list')
    # res = requests.get("http://dwz.2xb.cn/zaob")
    # url = json.loads(res.text)["imageUrl"]
    url = "https://api.jun.la/60s.php?format=image"
    for group in group_list:
        # 如果群号不在黑名单中
        if group["group_id"] not in [984625860, 1041873822]:
            await bot.call_api('send_group_msg', group_id=group["group_id"], message=f'[CQ:image,file={url}]')
