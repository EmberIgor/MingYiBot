from __future__ import annotations

import asyncio
import re
import unittest

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

import src.plugins.coc7 as coc7
from src.plugins.coc7.dice import DiceRoll


class Coc7HiddenRollTest(unittest.TestCase):
    def test_hidden_roll_command_parses_expression_and_reason(self) -> None:
        expression_request = coc7._parse_roll_request(".rh2d6+3", command="rh")
        reason_request = coc7._parse_roll_request("。rh尝试驾驶汽车", command="rh")

        self.assertEqual(expression_request, coc7.RollRequest("2d6+3"))
        self.assertEqual(reason_request, coc7.RollRequest("1d100", "尝试驾驶汽车"))

    def test_hidden_roll_command_is_not_consumed_by_regular_roll_pattern(self) -> None:
        self.assertIsNone(re.match(coc7.ROLL_COMMAND_PATTERN, ".rh 1d6"))
        self.assertIsNotNone(re.match(coc7.HIDDEN_ROLL_COMMAND_PATTERN, ".rh 1d6"))
        self.assertIsNotNone(re.match(coc7.ROLL_COMMAND_PATTERN, ".rd50"))

    def test_hidden_roll_group_output_is_delivered_privately(self) -> None:
        bot = FakeBot(friends=[123])
        event = _group_event(".rh 1d6", user_id=123, group_id=456)
        output = coc7._format_hidden_roll_output(
            coc7.RollRequest("1d6", "侦查"),
            DiceRoll("1d6", 4, "1d6[4]"),
            event,
            group_name="茗懿测试群",
        )

        public_response = asyncio.run(coc7._deliver_hidden_roll_output(bot, event, output))

        self.assertEqual(public_response, "暗骰结果已私聊发送。")
        self.assertEqual(bot.sent_messages, [(123, output)])
        self.assertIn("暗骰结果（群：茗懿测试群）", output)
        self.assertNotIn("群 456", output)
        self.assertIn("理由：侦查", output)
        self.assertIn("最终结果为：4", output)

    def test_hidden_roll_friend_check_matches_user_id(self) -> None:
        bot = FakeBot(friends=[123])

        self.assertTrue(asyncio.run(coc7._is_bot_friend(bot, 123)))
        self.assertFalse(asyncio.run(coc7._is_bot_friend(bot, 456)))

    def test_hidden_roll_send_failure_prompts_to_add_friend(self) -> None:
        bot = FakeBot(friends=[], send_error=RuntimeError("not friend"))
        event = _group_event(".rh 1d6", user_id=123, group_id=456)

        public_response = asyncio.run(coc7._deliver_hidden_roll_output(bot, event, "暗骰结果"))

        self.assertEqual(public_response, coc7.HIDDEN_ROLL_ADD_FRIEND_TEXT)

    def test_hidden_roll_fetches_group_name(self) -> None:
        bot = FakeBot(group_names={456: "茗懿测试群"})
        event = _group_event(".rh 1d6", user_id=123, group_id=456)

        group_name = asyncio.run(coc7._fetch_group_name(bot, event))

        self.assertEqual(group_name, "茗懿测试群")

    def test_hidden_roll_private_output_returns_result_directly(self) -> None:
        bot = FakeBot()
        event = _private_event(".rh 1d6", user_id=123)
        output = coc7._format_hidden_roll_output(coc7.RollRequest("1d6"), DiceRoll("1d6", 4, "1d6[4]"), event)

        response = asyncio.run(coc7._deliver_hidden_roll_output(bot, event, output))

        self.assertEqual(response, output)
        self.assertEqual(bot.sent_messages, [])
        self.assertIn("暗骰结果", output)


class FakeBot:
    def __init__(
        self,
        *,
        friends: list[int] | None = None,
        send_error: Exception | None = None,
        group_names: dict[int, str] | None = None,
    ) -> None:
        self.friends = friends or []
        self.send_error = send_error
        self.group_names = group_names or {}
        self.sent_messages: list[tuple[int, str]] = []

    async def send_private_msg(self, *, user_id: int, message: str) -> None:
        if self.send_error:
            raise self.send_error
        self.sent_messages.append((user_id, message))

    async def get_friend_list(self) -> list[dict[str, int]]:
        return [{"user_id": user_id} for user_id in self.friends]

    async def get_group_info(self, *, group_id: int, no_cache: bool = False) -> dict[str, int | str]:
        return {"group_id": group_id, "group_name": self.group_names.get(group_id, "")}


def _group_event(message: str, *, user_id: int, group_id: int) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=1,
        message=Message(message),
        original_message=Message(message),
        raw_message=message,
        font=0,
        sender={"user_id": user_id, "nickname": "test", "card": "", "role": "member"},
        to_me=False,
        reply=None,
        group_id=group_id,
        anonymous=None,
    )


def _private_event(message: str, *, user_id: int) -> PrivateMessageEvent:
    return PrivateMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="friend",
        user_id=user_id,
        message_type="private",
        message_id=1,
        message=Message(message),
        original_message=Message(message),
        raw_message=message,
        font=0,
        sender={"user_id": user_id, "nickname": "test"},
        to_me=False,
        reply=None,
    )


if __name__ == "__main__":
    unittest.main()
