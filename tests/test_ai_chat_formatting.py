import unittest

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from src.plugins.ai_chat.data_source import ChatHandler


class QQPlainTextFormattingTests(unittest.TestCase):
    def test_converts_common_markdown_to_qq_plain_text(self) -> None:
        content = (
            "## 画面细节\n\n"
            "- **角色**：瑞克穿着白大褂\n"
            "- **传送门**：一个[绿色传送门](https://example.com)\n"
            "> 这是引用\n"
            "还可以使用 `命令`。"
        )

        result = ChatHandler._to_qq_plain_text(content)

        self.assertEqual(
            result,
            "画面细节\n\n"
            "· 角色：瑞克穿着白大褂\n"
            "· 传送门：一个绿色传送门（https://example.com）\n"
            "引用：这是引用\n"
            "还可以使用 命令。",
        )

    def test_preserves_numbered_lists_and_removes_code_fences(self) -> None:
        content = "```text\n1. 第一步\n2. 第二步\n```"

        self.assertEqual(ChatHandler._to_qq_plain_text(content), "1. 第一步\n2. 第二步")


if __name__ == "__main__":
    unittest.main()
