from __future__ import annotations

import base64
import math
import re
import time

from nonebot import get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata

from .config import Config
from .data_source import VVClient, VVImageError, VVNoResultError, VVResponseError, VVTimeoutError


__plugin_meta__ = PluginMetadata(
    name="vv",
    description="搜索并发送 VV 表情包。",
    usage=".vv 关键词\n。vv 关键词",
    config=Config,
)


config = get_plugin_config(Config)
client = VVClient(
    api_url=config.vv_api_url,
    image_base_url=config.vv_image_base_url,
    timeout_seconds=config.vv_timeout_seconds,
    index_cache_seconds=config.vv_index_cache_seconds,
)
cooldowns: dict[tuple[str, int], float] = {}
vv_command = on_regex(r"^[.。]vv(?:\s+|$)(.*)$", flags=re.IGNORECASE, priority=20, block=True)


def _parse_query(message: str) -> str:
    match = re.fullmatch(r"[.。]vv(?:\s+|$)(.*)", message, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _cooldown_key(event: MessageEvent) -> tuple[str, int]:
    if isinstance(event, GroupMessageEvent):
        return "group", event.group_id
    return "private", event.user_id


def _take_cooldown(key: tuple[str, int], *, now: float | None = None) -> int:
    current = time.monotonic() if now is None else now
    previous = cooldowns.get(key)
    if previous is not None:
        remaining = config.vv_cooldown_seconds - (current - previous)
        if remaining > 0:
            return math.ceil(remaining)
    cooldowns[key] = current
    return 0


async def _build_response(event: MessageEvent) -> MessageSegment | str:
    query = _parse_query(event.get_plaintext())
    if not query:
        return "用法：.vv 关键词"

    remaining = _take_cooldown(_cooldown_key(event))
    if remaining:
        return f"VV 查询冷却中，请等待 {remaining} 秒。"

    try:
        image = await client.fetch_best_image(query)
    except VVTimeoutError:
        logger.warning("VV search timed out")
        return "VV 搜索服务响应超时，请稍后再试。"
    except VVNoResultError:
        return "没有找到匹配的 VV 表情包。"
    except VVImageError as exc:
        logger.warning("VV image fetch failed: {}", type(exc).__name__)
        return "匹配到了台词，但暂时无法取得对应图片。"
    except VVResponseError as exc:
        logger.warning("VV search response failed: {}", type(exc).__name__)
        return "VV 搜索服务暂时不可用，请稍后再试。"
    except Exception as exc:
        logger.exception("Unexpected VV command failure: {}", type(exc).__name__)
        return "VV 搜索暂时失败，请稍后再试。"

    encoded = base64.b64encode(image).decode("ascii")
    return MessageSegment.image(f"base64://{encoded}")


@vv_command.handle()
async def handle_vv_command(event: MessageEvent) -> None:
    await vv_command.finish(await _build_response(event))
