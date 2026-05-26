import unittest
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


_PLUGIN_DIR = Path(__file__).resolve().parents[1] / "src" / "plugins" / "ai_chat"
_PACKAGE_NAME = "ai_chat_testpkg"
_STUBBED_NONEBOT = False
if "nonebot" not in sys.modules:
    nonebot = ModuleType("nonebot")
    nonebot.logger = SimpleNamespace(
        exception=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )
    sys.modules["nonebot"] = nonebot
    _STUBBED_NONEBOT = True

if _PACKAGE_NAME not in sys.modules:
    package = ModuleType(_PACKAGE_NAME)
    package.__path__ = [str(_PLUGIN_DIR)]  # type: ignore[attr-defined]
    sys.modules[_PACKAGE_NAME] = package

config_module = ModuleType(f"{_PACKAGE_NAME}.config")
config_module.Config = object
sys.modules[config_module.__name__] = config_module

role_store_module = ModuleType(f"{_PACKAGE_NAME}.role_store")
role_store_module.RoleStore = object
sys.modules[role_store_module.__name__] = role_store_module

_DATA_SOURCE_SPEC = spec_from_file_location(f"{_PACKAGE_NAME}.data_source", _PLUGIN_DIR / "data_source.py")
assert _DATA_SOURCE_SPEC is not None
ai_chat_data_source = module_from_spec(_DATA_SOURCE_SPEC)
sys.modules[_DATA_SOURCE_SPEC.name] = ai_chat_data_source
assert _DATA_SOURCE_SPEC.loader is not None
_DATA_SOURCE_SPEC.loader.exec_module(ai_chat_data_source)
if _STUBBED_NONEBOT:
    sys.modules.pop("nonebot", None)


class _FakeRoleStore:
    def get_prompt(self, role_name: str) -> str:
        return f"system:{role_name}"


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=" 看到了图片。 "),
                )
            ]
        )


class _FakeClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class AiChatHandlerTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_multimodal_message_is_sent_but_not_stored_in_history(self) -> None:
        config = SimpleNamespace(
            aichat_key="",
            aichat_baseurl="",
            aichat_model="vision-model",
            aichat_session_ttl_minutes=1440,
            aichat_history_limit=12,
        )
        handler = ai_chat_data_source.ChatHandler(config, _FakeRoleStore())
        client = _FakeClient()
        handler.client = client

        message = [
            {"type": "text", "text": "这张图里有什么？"},
            {"type": "image_url", "image_url": {"url": "https://example.test/cat.jpg"}},
        ]
        response = await handler.ask(
            message,
            "session-1",
            "default",
            "这张图里有什么？ [image]",
        )

        self.assertEqual(response, "看到了图片。")
        request = client.completions.calls[0]
        self.assertEqual(request["model"], "vision-model")
        self.assertEqual(request["messages"][-1]["content"], message)
        self.assertEqual(
            handler.histories["session-1"][-2]["content"],
            "这张图里有什么？ [image]",
        )

    async def test_base64_image_mode_inlines_image_before_request(self) -> None:
        config = SimpleNamespace(
            aichat_key="",
            aichat_baseurl="",
            aichat_model="vision-model",
            aichat_session_ttl_minutes=1440,
            aichat_history_limit=12,
            aichat_image_mode="base64",
            aichat_image_max_bytes=123,
        )
        handler = ai_chat_data_source.ChatHandler(config, _FakeRoleStore())
        client = _FakeClient()
        handler.client = client

        image_url = "https://example.test/cat.jpg"
        message = [
            {"type": "text", "text": "这张图里有什么？"},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
        with patch.object(
            ai_chat_data_source,
            "_download_image_as_data_url",
            return_value="data:image/jpeg;base64,Y2F0",
        ) as download_image:
            response = await handler.ask(
                message,
                "session-1",
                "default",
                "这张图里有什么？ [image]",
            )

        self.assertEqual(response, "看到了图片。")
        download_image.assert_called_once_with(image_url, 123)
        request_content = client.completions.calls[0]["messages"][-1]["content"]
        self.assertEqual(request_content[1]["image_url"]["url"], "data:image/jpeg;base64,Y2F0")
        self.assertEqual(message[1]["image_url"]["url"], image_url)
        self.assertEqual(
            handler.histories["session-1"][-2]["content"],
            "这张图里有什么？ [image]",
        )


class AiChatConfigTestCase(unittest.TestCase):
    def test_vapi_base_url_is_normalized_for_openai_sdk(self) -> None:
        normalize = ai_chat_data_source._normalize_openai_base_url

        self.assertEqual(normalize("https://api.gpt.ge"), "https://api.gpt.ge/v1")
        self.assertEqual(normalize("https://api.gpt.ge/v1/"), "https://api.gpt.ge/v1")
        self.assertEqual(
            normalize("https://api.gpt.ge/v1/chat/completions"),
            "https://api.gpt.ge/v1",
        )


if __name__ == "__main__":
    unittest.main()
