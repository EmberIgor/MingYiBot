from nonebot.rule import to_me
from nonebot.adapters import Message, Event
from nonebot.params import CommandArg
from nonebot.plugin import on_command

echo = on_command("echo", to_me())


@echo.handle()
async def handle_echo(event: Event, message: Message = CommandArg()):
    print("=================")
    print(f"event:{event.dict()}")
    print("=================")
    await echo.send(message=message)
