import random


def build_investigator() -> str:
    attributes = {
        "STR": _roll_3d6() * 5,
        "CON": _roll_3d6() * 5,
        "POW": _roll_3d6() * 5,
        "DEX": _roll_3d6() * 5,
        "APP": _roll_3d6() * 5,
        "SIZ": _roll_2d6_plus_6() * 5,
        "INT": _roll_2d6_plus_6() * 5,
        "EDU": _roll_2d6_plus_6() * 5,
        "LUCK": _roll_3d6() * 5,
    }
    hp = (attributes["CON"] + attributes["SIZ"]) // 10
    mp = attributes["POW"] // 5
    san = attributes["POW"]

    lines = [
        "COC7 快速调查员",
        " ".join(f"{name}:{value}" for name, value in attributes.items()),
        f"HP:{hp} MP:{mp} SAN:{san}",
        "说明: 未包含职业、技能点、年龄修正和背景字段。",
    ]
    return "\n".join(lines)


def _roll_3d6() -> int:
    return sum(random.randint(1, 6) for _ in range(3))


def _roll_2d6_plus_6() -> int:
    return sum(random.randint(1, 6) for _ in range(2)) + 6
