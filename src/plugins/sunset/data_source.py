"""Two sky indices, bounded collection, and conservative alerts."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import sys
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

if __package__:
    from .sources import (
        GLOW,
        LOCAL,
        TZ,
        city_key,
        fresh,
        instant,
        normalize_bundle,
        number,
    )
else:  # Read-only verification CLI; avoids importing NoneBot/plugin startup.
    from sources import (
        GLOW,
        LOCAL,
        TZ,
        city_key,
        fresh,
        instant,
        normalize_bundle,
        number,
    )

SunsetEvent = Literal["rise_1", "set_1", "rise_2", "set_2"]
EVENTS = ("rise_1", "set_1", "rise_2", "set_2")
# Compatibility names are opportunity-strength settings, never physical burn labels.
THRESHOLDS = {
    "不烧": 55,
    "微烧": 55,
    "小烧": 55,
    "中烧": 70,
    "大烧": 85,
    "爆烧": 95,
    "极烧": 95,
}
COLLECTION_BUDGET = 39.0
SOURCE_BUDGET = 18.0
CACHE_TTL = 300
MAX_CITIES = 2
_cache: OrderedDict[tuple[str, str], dict] = OrderedDict()
_inflight: dict[str, asyncio.Task] = {}
_waiters: dict[str, int] = {}


class SunsetError(RuntimeError):
    pass


def _now():
    return datetime.now(TZ)


async def _run_process(command, budget):
    """No executor threads: terminate/reap the entire worker + Node process group."""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=budget)
        if process.returncode:
            raise SunsetError(
                "source_worker_failed: " + stderr.decode(errors="replace")[:120]
            )
        return stdout
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def _run_worker(source, city, timeout):
    raw = await _run_process(
        [
            sys.executable,
            str(Path(__file__).with_name("sources.py")),
            source,
            city,
            "--timeout",
            str(timeout),
        ],
        SOURCE_BUDGET,
    )
    return json.loads(raw)


async def _collect(city, timeout):
    forecasts, errors = [], []
    async with asyncio.timeout(COLLECTION_BUDGET):
        for source, label in [("glow", GLOW), ("local", LOCAL)]:
            key = (city, source)
            now = _now()
            cached = _cache.get(key)
            collected = instant(cached.get("collected_at")) if cached else None
            use_cache = (
                collected is not None
                and timedelta(0) <= now - collected < timedelta(seconds=CACHE_TTL)
                and collected.date() == now.date()
            )
            try:
                bundle = (
                    cached if use_cache else await _run_worker(source, city, timeout)
                )
                if not isinstance(bundle, dict):
                    raise ValueError("invalid_worker_response")
                errors.extend(label + ": " + str(x) for x in bundle.get("errors", []))
                if not (bundle.get("entries") or bundle.get("result")):
                    if not bundle.get("errors"):
                        errors.append(label + ": no_data")
                    continue
                parsed = normalize_bundle(bundle, _now())
                forecasts.extend(parsed)
                # Never replace a successful snapshot with failures/partial data.
                if (
                    not use_cache
                    and not bundle.get("errors")
                    and any(x["status"] == "valid" for x in parsed)
                ):
                    _cache[key] = bundle
                    _cache.move_to_end(key)
                    while len(_cache) > 64:
                        _cache.popitem(last=False)
            except (
                TimeoutError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
                RuntimeError,
            ) as exc:
                errors.append(label + ": " + (str(exc)[:120] or "collection_budget"))
    now = _now()
    responses = []
    for event in EVENTS:
        day = (now + timedelta(days=int(event[-1]) - 1)).date().isoformat()
        rows = [
            f
            for f in forecasts
            if f["date"] == day and f["event"] == event.split("_")[0]
        ]
        responses.append(
            (event, dict(city=city, date=day, forecasts=rows, errors=list(errors)))
        )
    return responses


async def fetch_sunset_events(
    location: str, api_url: str = "", model: str = "", timeout_seconds: float = 5
) -> list[tuple[SunsetEvent, dict[str, Any]]]:
    # Legacy api_url/model accepted for config compatibility; never requested.
    city = city_key(location)
    if not 2 <= len(city) <= 80:
        raise SunsetError("请输入明确城市，例如：.sun 上海")
    try:
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise SunsetError("SUNSET_TIMEOUT_SECONDS 必须为正数") from None
    task = _inflight.get(city)
    if task is None:
        if len(_inflight) >= MAX_CITIES:
            raise SunsetError("朝晚霞查询繁忙，请稍后再试")
        task = asyncio.create_task(_collect(city, min(5, timeout)))
        _inflight[city] = task
        _waiters[city] = 0
    _waiters[city] += 1
    try:
        return await asyncio.shield(task)
    except TimeoutError:
        raise SunsetError("朝晚霞采集达到总时间预算，数据未知") from None
    finally:
        _waiters[city] -= 1
        if _waiters[city] == 0:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            _inflight.pop(city, None)
            _waiters.pop(city, None)


async def build_sunset_report(location, api_url="", model="", timeout_seconds=5):
    return format_sunset_report(
        await fetch_sunset_events(location, api_url, model, timeout_seconds)
    )


def opportunity_strength(f, now):
    event = instant(f.get("event_time"))
    if (
        f.get("status") != "valid"
        or event is None
        or event <= now
        or event.date().isoformat() != f.get("date")
    ):
        return 0
    cloud = f.get("cloud_evidence") or {}
    mid, high, low = (number(cloud.get(k)) for k in ("mid", "high", "low"))
    if mid is None or high is None or low is None or mid + high < 15 or low > 50:
        return 0
    w = f.get("weather") or {}
    if f.get("source") == GLOW:
        p, q = number(f.get("probability")), number(f.get("quality"))
        if (
            p is None
            or q is None
            or p < 30
            or not fresh(f.get("quality_valid_until"), now)
            or not fresh(f.get("probability_valid_until"), now)
        ):
            return 0
        if (
            not fresh(f.get("action_valid_until"), now)
            or f.get("action_state") != "current"
            or f.get("source_status") in ("no_opportunity", "insufficient_data")
        ):
            return 0
        fields = (f.get("freshness") or {}).get("fields") or {}
        if any(
            fields.get(k) != "valid"
            for k in ("cloudHigh", "cloudMid", "cloudLow", "precipitation")
        ):
            return 0
        if (
            number(w.get("precipitationRateMmH"), 1e6) != 0
            or w.get("isPrecipitating") is not False
            or w.get("blocksSunset") is not False
        ):
            return 0
        return q
    if f.get("source") == LOCAL:
        if (
            not fresh(f.get("valid_until"), now)
            or number(w.get("precipitation"), 1e6) != 0
            or w.get("rain_near") != 0
            or w.get("rain_early") != 0
        ):
            return 0
        pop = number(w.get("pop_max"))
        if pop is None or pop >= 40:
            return 0
        return number(f.get("score")) or 0
    return 0


def _metric(value):
    return "未知" if value is None else f"{value:g}/100"


def _source_line(f, now):
    source = f["source"]
    event = instant(f.get("event_time"))
    clock = event.strftime("%Y-%m-%d %H:%M") if event else "未知时间"
    if source == GLOW:
        metric = f"质量潜力 {_metric(f.get('quality'))}；出现估计 {_metric(f.get('probability'))}（未校准）"
    else:
        metric = f"启发式指数 {_metric(f.get('score'))}（非概率）"
    cloud = f.get("cloud_evidence") or {}
    evidence = "/".join(
        "未知" if cloud.get(k) is None else f"{cloud[k]:g}"
        for k in ("low", "mid", "high")
    )
    status = "passed" if event and event <= now else f.get("status", "unknown")
    labels = {
        "valid": "有效",
        "passed": "已过",
        "stale": "已过期，未知",
        "unknown": "数据未知",
    }
    return f"{source} {clock}：{metric}；低/中/高云 {evidence}%；{labels.get(status, '数据未知')}"


def format_sunset_report(responses, *, now=None):
    now = now or _now()
    city = responses[0][1].get("city", "未知城市") if responses else "未知城市"
    lines = [f"【{city}】朝晚霞（北京时间）"]
    errors = set()
    strengths = []
    for event, data in responses:
        label = "朝霞" if event.startswith("rise") else "晚霞"
        lines.append(f"{data.get('date', '未知日期')} {label}")
        rows = data.get("forecasts") or []
        if not rows:
            lines.append("暂无有效来源，情况未知")
        for f in rows:
            lines.append(_source_line(f, now))
            strengths.append(opportunity_strength(f, now))
        errors.update(data.get("errors") or [])
    strength = max(strengths, default=0)
    if strength >= 70:
        lines.append("建议：有较强机会信号，可在附近开阔处守候；不保证成霞。")
    elif strength >= 55:
        lines.append("建议：可顺道观察，暂不建议专程远行。")
    else:
        lines.append("建议：有效证据暂不支持专程出行；未知数据不能当作无霞。")
    if errors:
        lines.append("部分来源未知：" + "；".join(sorted(errors)))
    lines.append(
        "Glow 仅提供晚霞；两源可能共享 Open-Meteo，不能当独立投票或平均。静态评分缺少方向光路验证。"
    )
    return "\n".join(lines)


def build_sunset_alert(responses, threshold_level="中烧", *, now=None):
    now = now or _now()
    threshold = THRESHOLDS.get(threshold_level)
    if threshold is None:
        return ""
    selected = []
    for event, data in responses:
        rows = [
            f
            for f in data.get("forecasts", [])
            if opportunity_strength(f, now) >= threshold
        ]
        if rows:
            # Include remaining evidence only for future events. Sources may
            # disagree on the event minute; a passed source must never be sent.
            future = [
                f
                for f in data.get("forecasts", [])
                if (when := instant(f.get("event_time"))) is not None
                and when > now
                and f.get("status") != "passed"
            ]
            selected.append((event, dict(data, forecasts=future)))
    if not selected:
        return ""
    return (
        f"朝晚霞机会提醒：保守机会强度阈值 {threshold}/100（非物理烧级）\n"
        + format_sunset_report(selected, now=now)
    )


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Read-only live verification; never imports QQ, startup, or database modules"
    )
    parser.add_argument("cities", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    async def verify():
        for city in args.cities:
            started = time.monotonic()
            responses = await fetch_sunset_events(city)
            result = dict(
                city=city,
                snapshot_time=_now().isoformat(),
                elapsed_seconds=round(time.monotonic() - started, 3),
                events=responses,
                report=format_sunset_report(responses),
                alert_preview=build_sunset_alert(responses),
            )
            print(
                json.dumps(result, ensure_ascii=False, allow_nan=False)
                if args.json
                else result["report"],
                flush=True,
            )

    asyncio.run(verify())
