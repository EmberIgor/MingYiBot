import os
import sys
import nonebot
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

sys.path.append(f"{os.getcwd()}/src/tools")

nonebot.init()

if get_driver().config.use_proxy == "True":
    os.environ["http_proxy"] = get_driver().config.http_proxy
    os.environ["https_proxy"] = get_driver().config.https_proxy
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)

nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
