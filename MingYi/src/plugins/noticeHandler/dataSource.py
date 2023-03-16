import requests


async def get_yi_yan():
    res = requests.get(f'https://v1.hitokoto.cn/').json()
    return res
