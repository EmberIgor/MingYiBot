from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment


ping = on_command("ping", aliases={"状态"}, priority=10, block=True)
status_alias = on_regex(r"^状态$", priority=10, block=True)


@ping.handle()
async def handle_ping(event: MessageEvent) -> None:
    await ping.finish(MessageSegment.text("pong"))


@status_alias.handle()
async def handle_status_alias(event: MessageEvent) -> None:
    await status_alias.finish(MessageSegment.text("pong"))
