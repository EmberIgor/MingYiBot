import random
import re
from dataclasses import dataclass


class DiceError(ValueError):
    pass


@dataclass(frozen=True)
class DiceRoll:
    expression: str
    total: int
    detail: str


@dataclass(frozen=True)
class D100Roll:
    value: int
    tens: list[int]
    unit: int
    mode: str = "normal"

    @property
    def detail(self) -> str:
        if self.mode == "normal":
            return f"d100={self.value}"
        tens_text = "/".join(f"{tens * 10:02d}" for tens in self.tens)
        label = "奖励骰" if self.mode == "bonus" else "惩罚骰"
        return f"{label} 十位[{tens_text}] 个位[{self.unit}] => {self.value}"


@dataclass(frozen=True)
class CheckResult:
    skill_name: str
    skill_value: int
    roll: D100Roll
    rank: str

    @property
    def is_success(self) -> bool:
        return self.rank in {"大成功", "极难成功", "困难成功", "普通成功"}


_TERM_RE = re.compile(r"([+-]?)\s*(?:(\d*)d(\d+)|(\d+))", re.IGNORECASE)


def roll_expression(expression: str) -> DiceRoll:
    source = expression.strip().replace(" ", "")
    if not source:
        raise DiceError("请输入骰子表达式，例如 1d100 或 2d6+3。")

    position = 0
    total = 0
    details: list[str] = []
    for match in _TERM_RE.finditer(source):
        if match.start() != position:
            raise DiceError("骰子表达式格式不正确。")
        sign_text, count_text, sides_text, number_text = match.groups()
        sign = -1 if sign_text == "-" else 1
        if sides_text:
            count = int(count_text or "1")
            sides = int(sides_text)
            if count < 1 or count > 100:
                raise DiceError("单次最多投 100 个骰子。")
            if sides < 2 or sides > 1000:
                raise DiceError("骰子面数必须在 2 到 1000 之间。")
            rolls = [random.randint(1, sides) for _ in range(count)]
            subtotal = sum(rolls)
            total += sign * subtotal
            prefix = "-" if sign < 0 else "+" if details else ""
            details.append(f"{prefix}{count}d{sides}[{','.join(map(str, rolls))}]")
        else:
            number = int(number_text)
            total += sign * number
            prefix = "-" if sign < 0 else "+" if details else ""
            details.append(f"{prefix}{number}")
        position = match.end()

    if position != len(source):
        raise DiceError("骰子表达式格式不正确。")

    return DiceRoll(expression=source, total=total, detail=" ".join(details))


def roll_d100(mode: str = "normal", count: int = 1) -> D100Roll:
    if mode not in {"normal", "bonus", "penalty"}:
        raise DiceError("未知的 d100 模式。")
    if count < 1 or count > 2:
        raise DiceError("奖励骰/惩罚骰数量暂时支持 1 到 2 个。")

    unit = random.randint(0, 9)
    if mode == "normal":
        tens = random.randint(0, 9)
        return D100Roll(value=_d100_value(tens, unit), tens=[tens], unit=unit)

    tens_rolls = [random.randint(0, 9) for _ in range(count + 1)]
    chosen_tens = min(tens_rolls) if mode == "bonus" else max(tens_rolls)
    return D100Roll(
        value=_d100_value(chosen_tens, unit),
        tens=tens_rolls,
        unit=unit,
        mode=mode,
    )


def coc7_check(skill_value: int, skill_name: str = "检定", mode: str = "normal") -> CheckResult:
    if skill_value < 1 or skill_value > 100:
        raise DiceError("技能值必须在 1 到 100 之间。")

    roll = roll_d100(mode)
    return CheckResult(
        skill_name=skill_name or "检定",
        skill_value=skill_value,
        roll=roll,
        rank=judge_check(roll.value, skill_value),
    )


def judge_check(roll: int, skill_value: int) -> str:
    if roll == 1:
        return "大成功"
    if _is_fumble(roll, skill_value):
        return "大失败"
    if roll <= skill_value // 5:
        return "极难成功"
    if roll <= skill_value // 2:
        return "困难成功"
    if roll <= skill_value:
        return "普通成功"
    return "失败"


def format_check(result: CheckResult) -> str:
    return (
        f"{result.skill_name} {result.skill_value}: {result.roll.value} "
        f"=> {result.rank}\n{result.roll.detail}"
    )


def format_roll(result: DiceRoll) -> str:
    values = _format_roll_values(result.detail)
    return f"{result.expression}的投掷结果是[{values}]\n最终结果为：{result.total}"


def _format_roll_values(detail: str) -> str:
    rolls: list[str] = []
    for values in re.findall(r"\[([\d,]+)\]", detail):
        rolls.extend(value for value in values.split(",") if value)
    return "，".join(rolls)


def _d100_value(tens: int, unit: int) -> int:
    value = tens * 10 + unit
    return 100 if value == 0 else value


def _is_fumble(roll: int, skill_value: int) -> bool:
    if skill_value < 50:
        return roll >= 96
    return roll == 100
