import unittest

import nonebot

nonebot.init()

from src.plugins.coc7.character import build_investigator
from src.plugins.coc7 import _parse_coc_count, _parse_roll_expression
from src.plugins.coc7.dice import DiceError, DiceRoll, format_roll, judge_check, roll_expression


class Coc7TestCase(unittest.TestCase):
    def test_roll_expression_supports_basic_dice_and_modifier(self) -> None:
        result = roll_expression("2d6+3")

        self.assertGreaterEqual(result.total, 5)
        self.assertLessEqual(result.total, 15)
        self.assertEqual(result.expression, "2d6+3")
        self.assertIn("2d6[", result.detail)

    def test_format_roll_uses_natural_text(self) -> None:
        result = DiceRoll(expression="3d100+3", total=78, detail="3d100[25,20,30] +3")

        self.assertEqual(format_roll(result), "3d100+3的投掷结果是[25，20，30]\n最终结果为：78")

    def test_roll_command_accepts_expression_without_space(self) -> None:
        self.assertEqual(_parse_roll_expression(".r1d100"), "1d100")
        self.assertEqual(_parse_roll_expression("。r2d6+3"), "2d6+3")
        self.assertEqual(_parse_roll_expression(".r"), "")

    def test_roll_command_accepts_rd_shorthand(self) -> None:
        self.assertEqual(_parse_roll_expression("。rd"), "")
        self.assertEqual(_parse_roll_expression("。rd50"), "1d50")
        self.assertEqual(_parse_roll_expression(".rd50+2"), "1d50+2")

    def test_coc_command_accepts_optional_count(self) -> None:
        self.assertEqual(_parse_coc_count(".coc"), 1)
        self.assertEqual(_parse_coc_count(".coc3"), 3)
        self.assertEqual(_parse_coc_count("。coc 10"), 10)

    def test_coc_command_rejects_count_out_of_range(self) -> None:
        with self.assertRaisesRegex(DiceError, "1 到 10"):
            _parse_coc_count(".coc11")

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
