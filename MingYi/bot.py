import os
import sys
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

sys.path.append(f"{os.getcwd()}/src/tools")

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)

nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
