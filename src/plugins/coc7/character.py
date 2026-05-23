import random


def build_investigator() -> str:
    attributes = {
        "力量": _roll_3d6() * 5,
        "体质": _roll_3d6() * 5,
        "意志": _roll_3d6() * 5,
        "敏捷": _roll_3d6() * 5,
        "外貌": _roll_3d6() * 5,
        "体型": _roll_2d6_plus_6() * 5,
        "智力": _roll_2d6_plus_6() * 5,
        "教育": _roll_2d6_plus_6() * 5,
        "幸运": _roll_3d6() * 5,
    }
    hp = (attributes["体质"] + attributes["体型"]) // 10
    mp = attributes["意志"] // 5
    san = attributes["意志"]

    lines = [
        "COC7 快速调查员",
        " ".join(f"{name}:{value}" for name, value in attributes.items()),
        f"生命值:{hp} 魔法值:{mp} 理智:{san}",
    ]
    return "\n".join(lines)


def _roll_3d6() -> int:
    return sum(random.randint(1, 6) for _ in range(3))


def _roll_2d6_plus_6() -> int:
    return sum(random.randint(1, 6) for _ in range(2)) + 6
