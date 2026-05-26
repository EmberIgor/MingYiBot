import re

from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata

from .character import build_investigator
from .dice import DiceError, coc7_check, format_check, format_roll, roll_expression


__plugin_meta__ = PluginMetadata(
    name="coc7",
    description="COC7 核心骰子和快速建卡。",
    usage=(
        ".r 1d100\n"
        ".ra 技能名 技能值\n"
        ".coc [数量]"
    ),
)


roll_command = on_regex(r"^[.。]r(?![abp])\s*(.*)$", priority=15, block=True)
check_command = on_regex(r"^[.。]ra\s+(.+)$", priority=14, block=True)
coc_command = on_regex(r"^[.。]coc\s*(\d*)$", priority=14, block=True)


@roll_command.handle()
async def handle_roll(event: MessageEvent) -> None:
    expression = _parse_roll_expression(_message_text(event))
    if not expression:
        expression = "1d100"
    try:
        result = roll_expression(expression)
    except DiceError as exc:
        await roll_command.finish(str(exc))
    await roll_command.finish(format_roll(result))


@check_command.handle()
async def handle_check(event: MessageEvent) -> None:
    try:
        skill_name, skill_value = _parse_named_check(_message_text(event), "ra")
        result = coc7_check(skill_value, skill_name)
    except DiceError as exc:
        await check_command.finish(str(exc))
    await check_command.finish(format_check(result))


@coc_command.handle()
async def handle_coc(event: MessageEvent) -> None:
    try:
        count = _parse_coc_count(_message_text(event))
    except DiceError as exc:
        await coc_command.finish(str(exc))
    await coc_command.finish(_build_investigators(count))


def _message_text(event: MessageEvent) -> str:
    return event.get_plaintext().strip()


def _parse_roll_expression(message: str) -> str:
    expression = re.sub(r"^[.。]r(?![abp])\s*", "", message, count=1).strip()
    if expression == "d":
        return ""
    if expression.startswith("d") and expression[1:2].isdigit():
        return f"1{expression}"
    return expression


def _parse_coc_count(message: str) -> int:
    count_text = re.sub(r"^[.。]coc\s*", "", message, count=1).strip()
    if not count_text:
        return 1
    count = int(count_text)
    if count < 1 or count > 10:
        raise DiceError("快速生成调查员数量必须在 1 到 10 之间。")
    return count


def _build_investigators(count: int) -> str:
    if count == 1:
        return build_investigator()
    return "\n\n".join(f"第 {index} 位调查员\n{build_investigator()}" for index in range(1, count + 1))


def _parse_named_check(message: str, command: str) -> tuple[str, int]:
    content = re.sub(rf"^[.。]{re.escape(command)}\s*", "", message, count=1).strip()
    if not content:
        raise DiceError(f"用法: .{command} 技能名 技能值")

    match = re.match(r"^(?:(.*?)\s+)?(\d{1,3})$", content)
    if not match:
        raise DiceError(f"用法: .{command} 技能名 技能值")

    skill_name = (match.group(1) or "检定").strip()
    return skill_name, int(match.group(2))
