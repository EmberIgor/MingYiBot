from dataclasses import dataclass

from nonebot import get_plugin_config, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.plugin import PluginMetadata
from src.common.settings import get_runtime_settings_store

from .config import Config


__plugin_meta__ = PluginMetadata(
    name="repeater",
    description="群内连续出现相同消息达到 2 条时，机器人复读一次。",
    usage="群内任意成员连续发送相同消息，第二条出现时机器人自动复读一次。",
    config=Config,
)


@dataclass
class RepeatState:
    message_key: str
    message: Message
    count: int = 1
    repeated: bool = False


config = get_plugin_config(Config)
runtime_settings = get_runtime_settings_store()
group_states: dict[int, RepeatState] = {}
repeater = on_message(priority=90, block=False)


def _message_key(message: Message) -> str:
    return str(message).strip()


@repeater.handle()
async def handle_repeater(event: GroupMessageEvent) -> None:
    threshold = await runtime_settings.get_int_async(
        "repeater",
        "threshold",
        config.repeater_threshold,
        group_id=event.group_id,
    )
    if threshold < 2:
        group_states.pop(event.group_id, None)
        return

    message = event.get_message()
    message_key = _message_key(message)
    if not message_key:
        return

    state = group_states.get(event.group_id)
    if state is None or state.message_key != message_key:
        group_states[event.group_id] = RepeatState(message_key=message_key, message=message)
        return

    state.count += 1
    if state.count >= threshold and not state.repeated:
        state.repeated = True
        try:
            await repeater.send(state.message)
        except Exception as exc:
            logger.exception(
                "Repeater failed to send message in group {}: {}",
                event.group_id,
                exc,
            )
