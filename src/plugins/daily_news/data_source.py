import asyncio
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class DailyNewsError(RuntimeError):
    pass


def build_daily_news_image_url(api_url: str, encoding: str) -> str:
    if encoding not in {"image", "image-proxy"}:
        raise DailyNewsError("每日新闻图片编码配置无效。")

    separator = "&" if "?" in api_url else "?"
    return f"{api_url}{separator}{urlencode({'encoding': encoding})}"


async def fetch_daily_news_date(api_url: str) -> str:
    return await asyncio.to_thread(_fetch_daily_news_date, api_url)


def _fetch_daily_news_date(api_url: str) -> str:
    separator = "&" if "?" in api_url else "?"
    url = f"{api_url}{separator}{urlencode({'encoding': 'json'})}"
    request = Request(
        url,
        headers={
            "User-Agent": "MingYiBot/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
    except OSError as exc:
        raise DailyNewsError("每日新闻接口请求失败，请稍后再试。") from exc

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DailyNewsError("每日新闻接口返回内容不是有效 JSON。") from exc

    if result.get("code") != 200:
        message = result.get("message") or "每日新闻接口返回失败。"
        raise DailyNewsError(str(message))

    data = result.get("data")
    if not isinstance(data, dict):
        raise DailyNewsError("每日新闻接口返回数据格式异常。")

    return str(data.get("date") or "").strip()
