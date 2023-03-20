import requests


async def getYiYan():
    res = requests.get(f'https://v1.hitokoto.cn/').json()
    return res
