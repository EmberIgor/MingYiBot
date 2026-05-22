import re

from nonebot import get_plugin_config, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata

from .ai import RuleAnswerer
from .character import build_investigator
from .config import Config
from .dice import DiceError, coc7_check, format_check, roll_expression


__plugin_meta__ = PluginMetadata(
    name="coc7",
    description="COC7 核心骰子、快速建卡和 AI 规则助手。",
    usage=(
        ".r 1d100\n"
        ".ra 技能名 技能值\n"
        ".rb 技能值\n"
        ".rp 技能值\n"
        ".sc 当前理智/成功损失/失败损失\n"
        ".coc\n"
        "/coc 问题"
    ),
    config=Config,
)


config = get_plugin_config(Config)
answerer = RuleAnswerer(config)

roll_command = on_regex(r"^[.。]r(?:\s+|$)(.*)$", priority=15, block=True)
check_command = on_regex(r"^[.。]ra\s+(.+)$", priority=14, block=True)
bonus_command = on_regex(r"^[.。]rb\s+(.+)$", priority=14, block=True)
penalty_command = on_regex(r"^[.。]rp\s+(.+)$", priority=14, block=True)
san_command = on_regex(r"^[.。]sc\s+(.+)$", priority=14, block=True)
coc_command = on_regex(r"^[.。]coc$", priority=14, block=True)
rule_command = on_regex(r"^/coc(?:\s+|$)(.*)$", priority=14, block=True)


@roll_command.handle()
async def handle_roll(event: MessageEvent) -> None:
    expression = re.sub(r"^[.。]r(?:\s+|$)", "", _message_text(event), count=1).strip()
    if not expression:
        expression = "1d100"
    try:
        result = roll_expression(expression)
    except DiceError as exc:
        await roll_command.finish(str(exc))
    await roll_command.finish(f"{result.expression} => {result.total}\n{result.detail}")


@check_command.handle()
async def handle_check(event: MessageEvent) -> None:
    try:
        skill_name, skill_value = _parse_named_check(_message_text(event), "ra")
        result = coc7_check(skill_value, skill_name)
    except DiceError as exc:
        await check_command.finish(str(exc))
    await check_command.finish(format_check(result))


@bonus_command.handle()
async def handle_bonus_check(event: MessageEvent) -> None:
    try:
        skill_name, skill_value = _parse_named_check(_message_text(event), "rb")
        result = coc7_check(skill_value, skill_name, mode="bonus")
    except DiceError as exc:
        await bonus_command.finish(str(exc))
    await bonus_command.finish(format_check(result))


@penalty_command.handle()
async def handle_penalty_check(event: MessageEvent) -> None:
    try:
        skill_name, skill_value = _parse_named_check(_message_text(event), "rp")
        result = coc7_check(skill_value, skill_name, mode="penalty")
    except DiceError as exc:
        await penalty_command.finish(str(exc))
    await penalty_command.finish(format_check(result))


@san_command.handle()
async def handle_san_check(event: MessageEvent) -> None:
    try:
        response = _san_check(re.sub(r"^[.。]sc\s*", "", _message_text(event), count=1).strip())
    except DiceError as exc:
        await san_command.finish(str(exc))
    await san_command.finish(response)


@coc_command.handle()
async def handle_coc(event: MessageEvent) -> None:
    await coc_command.finish(build_investigator())


@rule_command.handle()
async def handle_rule_question(event: MessageEvent) -> None:
    question = re.sub(r"^/coc(?:\s+|$)", "", _message_text(event), count=1).strip()
    response = await answerer.answer(question)
    await rule_command.finish(MessageSegment.text(response))


def _message_text(event: MessageEvent) -> str:
    return event.get_plaintext().strip()


def _parse_named_check(message: str, command: str) -> tuple[str, int]:
    content = re.sub(rf"^[.。]{re.escape(command)}\s*", "", message, count=1).strip()
    if not content:
        raise DiceError(f"用法: .{command} 技能名 技能值")

    match = re.match(r"^(?:(.*?)\s+)?(\d{1,3})$", content)
    if not match:
        raise DiceError(f"用法: .{command} 技能名 技能值")

    skill_name = (match.group(1) or "检定").strip()
    return skill_name, int(match.group(2))


def _san_check(content: str) -> str:
    match = re.match(r"^(\d{1,3})/([^/]+)/([^/]+)$", content)
    if not match:
        raise DiceError("用法: .sc 当前理智/成功损失/失败损失，例如 .sc 60/1/1d6")

    san_value = int(match.group(1))
    if san_value < 0 or san_value > 99:
        raise DiceError("当前理智值必须在 0 到 99 之间。")

    success_loss_expression = match.group(2).strip()
    fail_loss_expression = match.group(3).strip()
    result = coc7_check(max(san_value, 1), "理智检定")
    loss_expression = success_loss_expression if result.is_success else fail_loss_expression
    loss = roll_expression(loss_expression)
    new_san = max(san_value - max(loss.total, 0), 0)
    return (
        f"{format_check(result)}\n"
        f"理智损失: {loss_expression} => {loss.total}\n"
        f"SAN: {san_value} -> {new_san}"
    )
