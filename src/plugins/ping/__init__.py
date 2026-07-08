from __future__ import annotations

from datetime import datetime
import time
from typing import Any

from nonebot import get_driver, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment


driver = get_driver()
ping = on_regex(r"^[.。](?:ping|状态)$", priority=10, block=True)
performance_test = on_regex(r"^[.。](?:性能测试|延迟测试|perf)$", priority=10, block=True)


@ping.handle()
async def handle_ping(event: MessageEvent) -> None:
    await ping.finish(MessageSegment.text("pong"))


@performance_test.handle()
async def handle_performance_test(event: MessageEvent) -> None:
    started_at = time.perf_counter()
    received_at = time.time()

    if not _is_superuser(event):
        await performance_test.finish(MessageSegment.text("只有管理员可以执行性能测试。"))

    await performance_test.finish(
        MessageSegment.text(build_performance_report(event, started_at=started_at, received_at=received_at))
    )


def build_performance_report(event: Any, *, started_at: float, received_at: float) -> str:
    processed_ms = max((time.perf_counter() - started_at) * 1000, 0)
    event_latency_ms = _calculate_event_latency_ms(getattr(event, "time", None), received_at)
    event_time_text = _format_event_time(getattr(event, "time", None))

    latency_text = f"{event_latency_ms:.0f} ms" if event_latency_ms is not None else "不可用"

    return (
        "性能测试结果\n"
        f"事件延迟：{latency_text}\n"
        f"处理耗时：{processed_ms:.0f} ms\n"
        f"事件时间：{event_time_text}\n"
        "说明：事件延迟受平台、OneBot、网络、队列和宿主机时钟影响。"
    )


def _is_superuser(event: MessageEvent) -> bool:
    user_id = str(event.user_id).strip()
    return user_id in {str(item).strip() for item in driver.config.superusers}


def _calculate_event_latency_ms(event_time: Any, received_at: float) -> float | None:
    try:
        timestamp = float(event_time)
    except (TypeError, ValueError):
        return None

    return max((received_at - timestamp) * 1000, 0)


def _format_event_time(event_time: Any) -> str:
    try:
        timestamp = float(event_time)
    except (TypeError, ValueError):
        return "不可用"

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
