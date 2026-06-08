from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import patch

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

import src.plugins.daily_news as daily_news


class DailyNewsCommandTest(unittest.TestCase):
    def test_manual_command_ignores_group_push_setting(self) -> None:
        original_settings = daily_news.runtime_settings
        daily_news.runtime_settings = FailingRuntimeSettings()
        try:
            with (
                patch("src.plugins.daily_news._daily_news_is_today", return_value=True),
                patch("src.plugins.daily_news._build_daily_news_message", return_value="news-message"),
            ):
                response = asyncio.run(daily_news._build_today_news_command_response(_group_event(100)))
        finally:
            daily_news.runtime_settings = original_settings

        self.assertEqual(response, "news-message")

    def test_scheduled_push_still_respects_group_setting(self) -> None:
        bot = FakeBot(groups=[100])
        original_settings = daily_news.runtime_settings
        daily_news.runtime_settings = DisabledRuntimeSettings()
        try:
            asyncio.run(daily_news._send_to_bot_groups(bot, "news-message"))
        finally:
            daily_news.runtime_settings = original_settings

        self.assertEqual(bot.sent_groups, [])


class FailingRuntimeSettings:
    async def get_bool_async(self, *_: Any, **__: Any) -> bool:
        raise AssertionError("manual daily news command should not check group push settings")


class DisabledRuntimeSettings:
    async def get_bool_async(self, *_: Any, **__: Any) -> bool:
        return False


class FakeBot:
    self_id = 1

    def __init__(self, *, groups: list[int]) -> None:
        self.groups = groups
        self.sent_groups: list[tuple[int, str]] = []

    async def get_group_list(self) -> list[dict[str, int]]:
        return [{"group_id": group_id} for group_id in self.groups]

    async def send_group_msg(self, *, group_id: int, message: str) -> None:
        self.sent_groups.append((group_id, message))


def _group_event(group_id: int) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=1,
        message=Message(".今日新闻"),
        original_message=Message(".今日新闻"),
        raw_message=".今日新闻",
        font=0,
        sender={"user_id": 123, "nickname": "test", "card": "", "role": "member"},
        to_me=False,
        reply=None,
        group_id=group_id,
        anonymous=None,
    )


if __name__ == "__main__":
    unittest.main()
