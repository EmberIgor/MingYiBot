from dataclasses import dataclass

from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="repeater",
    description="群内连续出现相同消息达到 2 条时，机器人复读一次。",
    usage="群内任意成员连续发送相同消息，第二条出现时机器人自动复读一次。",
)


@dataclass
class RepeatState:
    message_key: str
    message: Message
    count: int = 1
    repeated: bool = False


group_states: dict[int, RepeatState] = {}
repeater = on_message(priority=90, block=False)


def _message_key(message: Message) -> str:
    return str(message).strip()


@repeater.handle()
async def handle_repeater(event: GroupMessageEvent) -> None:
    message = event.get_message()
    message_key = _message_key(message)
    if not message_key:
        return

    state = group_states.get(event.group_id)
    if state is None or state.message_key != message_key:
        group_states[event.group_id] = RepeatState(message_key=message_key, message=message)
        return

    state.count += 1
    if state.count >= 2 and not state.repeated:
        state.repeated = True
        await repeater.send(state.message)
