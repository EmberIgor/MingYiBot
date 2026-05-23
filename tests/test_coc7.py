import unittest

import nonebot

nonebot.init()

from src.plugins.coc7.character import build_investigator
from src.plugins.coc7.dice import DiceError, judge_check, roll_expression


class Coc7TestCase(unittest.TestCase):
    def test_roll_expression_supports_basic_dice_and_modifier(self) -> None:
        result = roll_expression("2d6+3")

        self.assertGreaterEqual(result.total, 5)
        self.assertLessEqual(result.total, 15)
        self.assertEqual(result.expression, "2d6+3")
        self.assertIn("2d6[", result.detail)

    def test_roll_expression_rejects_too_many_dice(self) -> None:
        with self.assertRaisesRegex(DiceError, "最多"):
            roll_expression("101d6")

    def test_coc7_check_rank_boundaries(self) -> None:
        self.assertEqual(judge_check(1, 50), "大成功")
        self.assertEqual(judge_check(10, 50), "极难成功")
        self.assertEqual(judge_check(25, 50), "困难成功")
        self.assertEqual(judge_check(50, 50), "普通成功")
        self.assertEqual(judge_check(51, 50), "失败")
        self.assertEqual(judge_check(96, 49), "大失败")
        self.assertEqual(judge_check(100, 50), "大失败")

    def test_quick_investigator_contains_core_fields(self) -> None:
        output = build_investigator()

        for field in ["力量", "体质", "意志", "敏捷", "外貌", "体型", "智力", "教育", "幸运", "生命值", "魔法值", "理智"]:
            self.assertIn(f"{field}:", output)
        self.assertNotIn("说明:", output)


if __name__ == "__main__":
    unittest.main()
