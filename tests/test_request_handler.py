from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

import src.plugins.request_handler as request_handler


class RequestHandlerTest(unittest.TestCase):
    def test_friend_request_notification_mentions_user_and_comment(self) -> None:
        event = SimpleNamespace(user_id=123456, comment="我是新好友")

        message = request_handler.build_friend_request_notification(event)

        self.assertIn("已自动通过好友请求。", message)
        self.assertIn("好友 QQ：123456", message)
        self.assertIn("验证信息：我是新好友", message)

    def test_group_invite_notification_mentions_group_inviter_and_empty_comment(self) -> None:
        event = SimpleNamespace(group_id=10001, user_id=20002, comment="")

        message = request_handler.build_group_invite_notification(event, group_name="茗懿测试群")

        self.assertIn("已自动通过群邀请，机器人已加入群聊。", message)
        self.assertIn("群名：茗懿测试群", message)
        self.assertIn("群号：10001", message)
        self.assertIn("邀请人 QQ：20002", message)
        self.assertIn("验证信息：无", message)

    def test_group_invite_rule_only_matches_invites(self) -> None:
        self.assertTrue(request_handler._is_group_invite_event(SimpleNamespace(sub_type="invite")))
        self.assertFalse(request_handler._is_group_invite_event(SimpleNamespace(sub_type="add")))

    def test_notify_superusers_filters_invalid_ids(self) -> None:
        bot = FakeBot()

        with patch.object(request_handler, "get_superuser_ids", return_value=["123", "abc", "456"]):
            asyncio.run(request_handler._notify_superusers(bot, "通知内容"))

        self.assertEqual(
            bot.sent_messages,
            [
                (123, "通知内容"),
                (456, "通知内容"),
            ],
        )


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []

    async def send_private_msg(self, *, user_id: int, message: str) -> None:
        self.sent_messages.append((user_id, message))


if __name__ == "__main__":
    unittest.main()
