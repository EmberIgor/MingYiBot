from __future__ import annotations

import asyncio
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nonebot import get_driver, get_plugin_config, logger, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata

from .config import Config


__plugin_meta__ = PluginMetadata(
    name="deploy",
    description="管理员手动触发 Watchtower 立即检查并更新镜像。",
    usage=".更新\n.部署更新",
    config=Config,
)


config = get_plugin_config(Config)
driver = get_driver()
deploy_update = on_regex(r"^[.。](?:更新|部署更新)$", priority=8, block=True)


@deploy_update.handle()
async def handle_deploy_update(event: MessageEvent) -> None:
    if not _is_superuser(event):
        await deploy_update.finish(MessageSegment.text("只有管理员可以触发部署更新。"))

    if not config.watchtower_http_api_token:
        await deploy_update.finish(MessageSegment.text("Watchtower HTTP API token 未配置，无法触发更新。"))

    try:
        await asyncio.to_thread(_trigger_watchtower_update)
    except DeployUpdateError as exc:
        logger.warning("Watchtower update trigger failed: {}", exc)
        await deploy_update.finish(MessageSegment.text(f"触发镜像更新失败：{exc}"))

    await deploy_update.finish(MessageSegment.text("已触发 Watchtower 检查更新，若有新镜像会自动拉取并重启。"))


def _is_superuser(event: MessageEvent) -> bool:
    user_id = str(event.user_id).strip()
    return user_id in {str(item).strip() for item in driver.config.superusers}


def _trigger_watchtower_update() -> None:
    request = Request(
        _update_url(),
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {config.watchtower_http_api_token}"},
    )
    try:
        with urlopen(request, timeout=config.watchtower_http_timeout_seconds) as response:
            if response.status < 200 or response.status >= 300:
                raise DeployUpdateError(f"Watchtower 返回 HTTP {response.status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        message = f"Watchtower 返回 HTTP {exc.code}"
        if detail:
            message = f"{message}: {detail[:120]}"
        raise DeployUpdateError(message) from exc
    except URLError as exc:
        raise DeployUpdateError(str(exc.reason)) from exc
    except TimeoutError as exc:
        raise DeployUpdateError("请求 Watchtower 超时") from exc


def _update_url() -> str:
    separator = "&" if "?" in config.watchtower_http_api_url else "?"
    query = urlencode({"image": config.watchtower_update_image, "async": "true"})
    return f"{config.watchtower_http_api_url}{separator}{query}"


class DeployUpdateError(RuntimeError):
    pass
