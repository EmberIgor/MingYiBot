from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment


ping = on_command("ping", aliases={"状态"}, priority=10, block=True)


@ping.handle()
async def handle_ping(event: MessageEvent) -> None:
    await ping.finish(MessageSegment.text("pong"))
