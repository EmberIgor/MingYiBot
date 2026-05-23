import asyncio
import json
from datetime import datetime
from random import randint
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nonebot import logger


SunsetEvent = Literal["rise_1", "set_1", "rise_2", "set_2"]

EVENTS: tuple[SunsetEvent, ...] = ("rise_1", "set_1", "rise_2", "set_2")
EVENT_LABELS: dict[SunsetEvent, str] = {
    "rise_1": "今日",
    "set_1": "今日",
    "rise_2": "明日",
    "set_2": "明日",
}
EVENT_TIME_LABELS: dict[SunsetEvent, str] = {
    "rise_1": "日出时分",
    "set_1": "日落时分",
    "rise_2": "日出时分",
    "set_2": "日落时分",
}
BURN_LEVEL_RANKS = {
    "不烧": 0,
    "微烧": 1,
    "小烧": 2,
    "中烧": 3,
    "大烧": 4,
    "爆烧": 5,
    "极烧": 5,
}


class SunsetError(RuntimeError):
    pass


async def build_sunset_report(
    location: str,
    api_url: str,
    model: str,
    timeout_seconds: float,
) -> str:
    responses = await fetch_sunset_events(location, api_url, model, timeout_seconds)
    return format_sunset_report(responses)


async def fetch_sunset_events(
    location: str,
    api_url: str,
    model: str,
    timeout_seconds: float,
) -> list[tuple[SunsetEvent, dict[str, Any]]]:
    city = location.strip()
    if not city:
        raise SunsetError("请输入地点，例如：/sun 上海")

    tasks = [_fetch_event(api_url, city, event, model, timeout_seconds) for event in EVENTS]
    return list(await asyncio.gather(*tasks))


def format_sunset_report(responses: list[tuple[SunsetEvent, dict[str, Any]]]) -> str:
    lines: list[str] = []
    previous_day_label = ""
    for event, data in responses:
        day_label = EVENT_LABELS[event]
        if day_label != previous_day_label:
            header = _format_day_header(day_label, data)
            if header:
                if lines:
                    lines.append("")
                lines.append(header)
            previous_day_label = day_label

        lines.append(_format_event_line(event, data))

    return "\n".join(lines).strip()


def build_sunset_alert(
    responses: list[tuple[SunsetEvent, dict[str, Any]]],
    threshold_level: str = "中烧",
) -> str:
    matches = [
        (event, data)
        for event, data in responses
        if _event_reaches_threshold(data, threshold_level)
    ]
    if not matches:
        return ""

    city = _first_ok_value(responses, "place_holder") or _first_ok_value(responses, "display_city_name") or "默认城市"
    model = _first_ok_value(responses, "display_model")
    model_text = f"（{model}）" if model else ""
    lines = [f"火烧云提醒：{city}{model_text} 今日/明日可能达到{threshold_level}或以上。"]

    for event, data in matches:
        day_label = EVENT_LABELS[event]
        lines.append(f"{day_label}{_format_event_line(event, data)}")

    return "\n".join(lines)


async def _fetch_event(
    api_url: str,
    location: str,
    event: SunsetEvent,
    model: str,
    timeout_seconds: float,
) -> tuple[SunsetEvent, dict[str, Any]]:
    return await asyncio.to_thread(
        _fetch_event_sync,
        api_url,
        location,
        event,
        model,
        timeout_seconds,
    )


def _fetch_event_sync(
    api_url: str,
    location: str,
    event: SunsetEvent,
    model: str,
    timeout_seconds: float,
) -> tuple[SunsetEvent, dict[str, Any]]:
    params = {
        "query_id": str(randint(1, 10_000_000)),
        "intend": "select_city",
        "query_city": location,
        "event_date": "None",
        "event": event,
        "times": "None",
        "model": model,
    }

    try:
        separator = "&" if "?" in api_url else "?"
        url = f"{api_url}{separator}{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "MingYiBot/1.0"})
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise SunsetError("接口返回格式异常")
        return event, data
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError, SunsetError) as exc:
        logger.warning(
            "Sunset API request failed for location {} event {}: {}",
            location,
            event,
            exc,
        )
        return event, {"status": "error", "message": str(exc)}


def _format_day_header(day_label: str, data: dict[str, Any]) -> str:
    if data.get("status") != "ok":
        return f"{day_label}火烧云情况："

    city = str(data.get("place_holder") or data.get("display_city_name") or "未知地点")
    date_fmt = _format_date(str(data.get("tb_event_time", "")))
    if date_fmt:
        return f"{day_label}【{city}】火烧云（{date_fmt}）情况："
    return f"{day_label}【{city}】火烧云情况："


def _format_event_line(event: SunsetEvent, data: dict[str, Any]) -> str:
    label = EVENT_TIME_LABELS[event]
    if data.get("status") != "ok":
        reason = str(data.get("message") or data.get("status") or "获取失败")
        return f"{label}：获取失败（{reason}）"

    event_time = str(data.get("tb_event_time", "未知时间"))
    quality, level = _split_metric(str(data.get("tb_quality", "未知")))
    aod, aod_level = _split_metric(str(data.get("tb_aod", "未知")))

    details = f"{quality}"
    if level:
        details += f"（{level}）"
    if aod != "未知":
        details += f"，AOD {aod}"
        if aod_level:
            details += f"（{aod_level}）"

    return f"{label}（{event_time}）：{details}"


def _event_reaches_threshold(data: dict[str, Any], threshold_level: str) -> bool:
    if data.get("status") != "ok":
        return False

    _, level = _split_metric(str(data.get("tb_quality", "")))
    level_rank = _burn_level_rank(level)
    threshold_rank = _burn_level_rank(threshold_level)
    return level_rank >= threshold_rank


def _burn_level_rank(level: str) -> int:
    normalized = level.strip()
    if normalized in BURN_LEVEL_RANKS:
        return BURN_LEVEL_RANKS[normalized]

    for name in sorted(BURN_LEVEL_RANKS, key=len, reverse=True):
        if name in normalized:
            return BURN_LEVEL_RANKS[name]

    return -1


def _first_ok_value(responses: list[tuple[SunsetEvent, dict[str, Any]]], key: str) -> str:
    for _, data in responses:
        if data.get("status") == "ok" and data.get(key):
            return str(data[key])
    return ""


def _split_metric(value: str) -> tuple[str, str]:
    if "（" not in value:
        return value or "未知", ""
    score, rest = value.split("（", 1)
    return score, rest.rstrip("）")


def _format_date(event_time: str) -> str:
    date_text = event_time.split(" ", 1)[0]
    try:
        date_obj = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{date_obj.month}月{date_obj.day}日"
