import re
from dataclasses import dataclass

from nonebot import get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from src.common.ai import AIConfig, create_openai_client, extract_content, request_response

from .character import build_investigator
from .dice import DiceError, DiceRoll, coc7_check, format_check, format_roll, roll_expression


__plugin_meta__ = PluginMetadata(
    name="coc7",
    description="COC7 核心骰子和快速建卡。",
    usage=(
        ".r 1d100\n"
        ".r 尝试驾驶汽车\n"
        ".ra 技能名 技能值\n"
        ".coc [数量]"
    ),
)


roll_command = on_regex(r"^[.。]r(?![abp])\s*(.*)$", priority=15, block=True)
check_command = on_regex(r"^[.。]ra\s+(.+)$", priority=14, block=True)
coc_command = on_regex(r"^[.。]coc\s*(\d*)$", priority=14, block=True)
ai_config = get_plugin_config(AIConfig)
ai_client = create_openai_client(ai_config.ai_key, ai_config.ai_baseurl)
_ROLL_TERM_RE = re.compile(r"([+-]?)\s*(?:(\d*)d(\d+)|(\d+))", re.IGNORECASE)


@dataclass(frozen=True)
class RollRequest:
    expression: str
    reason: str = ""


@roll_command.handle()
async def handle_roll(event: MessageEvent) -> None:
    request = _parse_roll_request(_message_text(event))
    try:
        result = roll_expression(request.expression)
    except DiceError as exc:
        await roll_command.finish(str(exc))

    output = format_roll(result)
    commentary = await _generate_roll_commentary(request, result)
    if commentary:
        output = f"{output}\n\n{commentary}"
    await roll_command.finish(output)


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


def _parse_roll_request(message: str) -> RollRequest:
    content = re.sub(r"^[.。]r(?![abp])\s*", "", message, count=1).strip()
    if not content:
        return RollRequest("1d100")

    if content == "d":
        return RollRequest("1d100")

    if content.startswith("d") and content[1:2] and not content[1:2].isdigit() and not content[1:2].isspace():
        return RollRequest("1d100", content[1:].strip())

    expression = _normalize_roll_expression(content)
    if _looks_like_roll_expression(expression):
        return RollRequest(expression)

    first_token, separator, reason = content.partition(" ")
    if separator:
        expression = _normalize_roll_expression(first_token)
        if _looks_like_roll_expression(expression):
            return RollRequest(expression, reason.strip())

    return RollRequest("1d100", content)


def _parse_roll_expression(message: str) -> str:
    request = _parse_roll_request(message)
    if request.expression == "1d100" and not request.reason:
        return ""
    return request.expression


def _normalize_roll_expression(expression: str) -> str:
    expression = expression.strip()
    if expression == "d":
        return "1d100"
    if expression.startswith("d") and expression[1:2].isdigit():
        return f"1{expression}"
    return expression


def _looks_like_roll_expression(expression: str) -> bool:
    source = expression.strip().replace(" ", "")
    if not source:
        return False

    position = 0
    for match in _ROLL_TERM_RE.finditer(source):
        if match.start() != position:
            return False
        position = match.end()

    return position == len(source)


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


async def _generate_roll_commentary(request: RollRequest, result: DiceRoll) -> str:
    if not request.reason or not ai_client or not ai_config.ai_model:
        return ""

    try:
        response = await request_response(
            ai_client,
            model=ai_config.ai_model,
            instructions=_roll_commentary_instructions(),
            messages=[
                {
                    "role": "user",
                    "content": _format_roll_commentary_input(request, result),
                }
            ],
            web_search=False,
            stream=False,
        )
    except Exception as exc:
        logger.exception("COC7 roll commentary request failed: {}", exc)
        return ""

    return _clean_roll_commentary(extract_content(response))


def _roll_commentary_instructions() -> str:
    return (
        "你是 COC7 跑团里负责吐槽骰子结果的中文旁白。"
        "根据投掷理由和结果给 1 到 2 句短评，适合 QQ 群聊。"
        "不要改写骰子结果，不要讲规则，不要使用 Markdown。"
        "默认 d100 语境下，投掷结果越大代表越困难、越糟糕，越低代表越顺利。"
        "大成功或极端好运要兴奋一点，大失败或灾难性失误要更夸张一点。"
    )


def _format_roll_commentary_input(request: RollRequest, result: DiceRoll) -> str:
    return "\n".join(
        [
            f"投掷理由：{request.reason}",
            f"骰子表达式：{result.expression}",
            f"投掷明细：{result.detail}",
            f"最终值：{result.total}",
            f"判定语义：{_roll_judgement_text(result)}",
        ]
    )


def _roll_judgement_text(result: DiceRoll) -> str:
    expression = result.expression.replace(" ", "").lower()
    if expression not in {"d100", "1d100"}:
        return "这是自定义表达式，不套用 d100 成败等级；结合理由、最终值和骰子直觉做短评。"

    value = result.total
    if value == 1:
        return "1：极端好运，大成功，事情顺得夸张。"
    if value >= 96:
        return "96-100：灾难性失误，大失败，事情很可能朝离谱方向发展。"
    if value <= 5:
        return "1-5：完全没接触过的新手水平也能做到，几乎顺手就成。"
    if value <= 19:
        return "6-19：入门水平即可完成，整体比较顺利。"
    if value <= 49:
        return "20-49：普通人的日常熟练度或业余爱好者水平。"
    if value <= 74:
        return "50-74：需要专业人士水准，已经不算轻松。"
    if value <= 89:
        return "75-89：需要行业精英或资深专家水准，场面比较紧张。"
    return "90-95：接近世界顶尖高手或人类极限才能稳住。"


def _clean_roll_commentary(content: str) -> str:
    content = re.sub(r"^```(?:text)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"\s+", " ", content)
    return content[:120].strip()
