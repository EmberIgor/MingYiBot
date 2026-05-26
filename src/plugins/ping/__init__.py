from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment


ping = on_regex(r"^[.。](?:ping|状态)$", priority=10, block=True)


@ping.handle()
async def handle_ping(event: MessageEvent) -> None:
    await ping.finish(MessageSegment.text("pong"))
