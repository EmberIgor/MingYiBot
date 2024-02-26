from nonebot import on_regex, on_command
from nonebot.adapters import Event
from nonebot.typing import T_State
from .dataSource import *

dice_model = 'fast'
dice_order_pattern = r"\.?r\d*d\d+(?:/\d+)?"
dice_player = on_regex(dice_order_pattern)
dice_model_switch = on_command("切换骰子")


@dice_player.handle()
async def _(event: Event, state: T_State):
    global dice_model
    rolls, sides, threshold = dataSource.extract_dice_data(str(event.dict()['message']))
    dice_results, total, effect = dataSource.roll_dice(rolls, sides, threshold)
    chat_txt = (f'投掷了{rolls}个骰子。'
                f'投掷的结果为：{dice_results}。'
                f'点数总计为：{total}。'
                )
    if effect is not None:
        if effect:
            chat_txt += f'检定结果：成功。'
        else:
            chat_txt += f'检定结果：失败。'
    # chat_api_res_message = dataSource.chat(rolls, dice_results, total, effect)
    chat_api_res_message = dataSource.chat(rolls, dice_results, total, effect) if dice_model == 'chat' else chat_txt
    await dice_player.send(chat_api_res_message, at_sender=True)


@dice_model_switch.handle()
async def _():
    global dice_model
    dice_model = 'fast' if dice_model == 'chat' else 'chat'
    await dice_model_switch.send(f'骰子模式为:{dice_model}')
