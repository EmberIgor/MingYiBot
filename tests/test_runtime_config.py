from __future__ import annotations

import asyncio
import unittest
from typing import Any

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

import src.plugins.runtime_config as runtime_config


class RuntimeConfigCommandTest(unittest.TestCase):
    def test_message_archive_global_commands_are_supported(self) -> None:
        fake_settings = FakeRuntimeSettings()
        original_settings = runtime_config.runtime_settings
        runtime_config.runtime_settings = fake_settings
        try:
            enabled_response = asyncio.run(
                runtime_config._apply_scope_setting(
                    "群记录 开",
                    "global",
                    None,
                    123,
                    scope_label="全局",
                    allowed_settings=runtime_config.GLOBAL_SETTINGS,
                )
            )
            retention_response = asyncio.run(
                runtime_config._apply_scope_setting(
                    "群记录 保留 120",
                    "global",
                    None,
                    123,
                    scope_label="全局",
                    allowed_settings=runtime_config.GLOBAL_SETTINGS,
                )
            )
            reset_response = asyncio.run(
                runtime_config._apply_scope_setting(
                    "重置 群记录",
                    "global",
                    None,
                    123,
                    scope_label="全局",
                    allowed_settings=runtime_config.GLOBAL_SETTINGS,
                )
            )
        finally:
            runtime_config.runtime_settings = original_settings

        self.assertEqual(enabled_response, "已开启全局群消息记录。")
        self.assertEqual(retention_response, "已将全局群消息记录保留天数设为：120")
        self.assertEqual(reset_response, "已重置全局配置。")
        self.assertEqual(
            fake_settings.set_calls,
            [
                ("global", None, "message_archive", "enabled", True, 123),
                ("global", None, "message_archive", "retention_days", 120, 123),
            ],
        )
        self.assertEqual(fake_settings.delete_calls, [("global", None, "message_archive", "enabled")])

    def test_runtime_config_help_mentions_message_archive(self) -> None:
        self.assertIn(".配置 群记录 开/关", runtime_config._help_text(is_group=False))
        self.assertIn(".配置 群记录保留 90", runtime_config._help_text(is_group=True))


class FakeRuntimeSettings:
    def __init__(self) -> None:
        self.set_calls: list[tuple[str, int | None, str, str, Any, int]] = []
        self.delete_calls: list[tuple[str, int | None, str, str]] = []

    async def set_value_async(
        self,
        scope_type: str,
        scope_id: int | None,
        namespace: str,
        key: str,
        value: Any,
        *,
        updated_by: int,
    ) -> None:
        self.set_calls.append((scope_type, scope_id, namespace, key, value, updated_by))

    async def delete_value_async(
        self,
        scope_type: str,
        scope_id: int | None,
        namespace: str,
        key: str,
    ) -> bool:
        self.delete_calls.append((scope_type, scope_id, namespace, key))
        return True


if __name__ == "__main__":
    unittest.main()
