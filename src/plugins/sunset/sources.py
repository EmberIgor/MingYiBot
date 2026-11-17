"""Sky source parsing and isolated read-only collectors (no NoneBot imports).

Glow parsing adapted from glow_sunset_reference.py; local algorithm is pinned
verbatim from https://yb.zhuiguang.ren/assets/scoring.js. See assets/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import ssl
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import certifi

TZ = ZoneInfo("Asia/Shanghai")
GLOW = "Glow Sunset"
ENGINE = Path(__file__).with_name("assets") / "zhuiguang_scoring.js"
ENGINE_SHA256 = "c5fc3c407a473e2e30ac7bd53fd403be152786a0be3f6a5245c8f4d72539434a"
HOURLY = "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,relative_humidity_2m,visibility,wind_speed_10m,wind_direction_10m,precipitation,precipitation_probability,weather_code"
CURRENT = "precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,relative_humidity_2m,visibility"


def compute_local(city, forecast, air, now):
    if hashlib.sha256(ENGINE.read_bytes()).hexdigest() != ENGINE_SHA256:
        raise ValueError("scoring_engine_hash_mismatch")
    node = shutil.which("node")
    if not node:
        raise ValueError("node_runtime_missing")
    # Nulls in current observations are coerced to zero by the upstream engine.
    # Only use complete observations acquired within 30 minutes of this snapshot.
    forecast = dict(forecast)
    current = forecast.get("current") or {}
    observed = instant(str(current.get("time", "")) + "+08:00")
    if (
        not observed
        or not timedelta(0) <= now - observed <= timedelta(minutes=30)
        or any(number(current.get(k), 1e8) is None for k in CURRENT.split(","))
    ):
        forecast.pop("current", None)
    script = """const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const RealDate=Date; class Clock extends RealDate {constructor(...args){super(...(args.length?args:[input.now]));} static now(){return new RealDate(input.now).getTime();}}
const ctx={window:{},Date:Clock,Math};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{timeout:1000});
ctx.city=input.city;ctx.forecast=input.forecast;ctx.air=input.air;
console.log(JSON.stringify(vm.runInContext('window.HSY.computeCity(city,forecast,air)',ctx,{timeout:1000})));
"""
    result = subprocess.run(
        [node, "-e", script, str(ENGINE)],
        input=json.dumps(
            dict(city=city, forecast=forecast, air=air, now=now.isoformat()),
            allow_nan=False,
        ),
        capture_output=True,
        text=True,
        timeout=3,
        env=dict(os.environ, TZ="Asia/Shanghai"),
        check=True,
    )
    data = json.loads(result.stdout)
    if data.get("error") or data.get("today") is None:
        raise ValueError("incomplete_or_wrong_date_input")
    return data


def complete_window(hourly, event, before, after, fields):
    times = hourly.get("time") or []
    start, end = event + timedelta(minutes=before), event + timedelta(minutes=after)
    indices = [
        i
        for i, t in enumerate(times)
        if (dt := instant(str(t) + "+08:00")) and start <= dt <= end
    ]
    # All hourly samples intersecting this window must be present; never let the
    # static engine fill cloud/visibility/rain gaps with optimistic defaults.
    first = start.replace(minute=0, second=0, microsecond=0)
    if first < start:
        first += timedelta(hours=1)
    expected = {
        first + timedelta(hours=i)
        for i in range(max(0, int((end - first).total_seconds() // 3600) + 1))
    }
    actual = [instant(str(times[i]) + "+08:00") for i in indices]
    if not expected or len(actual) != len(expected) or set(actual) != expected:
        return False
    for field in fields:
        values = hourly.get(field) or []
        maximum = (
            100
            if field
            in (
                "cloud_cover",
                "cloud_cover_low",
                "cloud_cover_mid",
                "cloud_cover_high",
                "relative_humidity_2m",
                "precipitation_probability",
            )
            else 1e8
        )
        if any(i >= len(values) or number(values[i], maximum) is None for i in indices):
            return False
    return True


def normalize_local(data, fc, air, city, now, collected):
    if (
        data.get("id") != city["id"]
        or data.get("lat") != city["lat"]
        or data.get("lon") != city["lon"]
    ):
        raise ValueError("city_mismatch")
    if (
        fc.get("timezone") != "Asia/Shanghai"
        or abs(fc.get("latitude", 999) - city["lat"]) > 0.3
        or abs(fc.get("longitude", 999) - city["lon"]) > 0.3
    ):
        raise ValueError("forecast_location_or_timezone_mismatch")
    days = [data.get("today")] + list(data.get("days") or [])[:1]
    results = []
    for offset in range(2):
        day = (now + timedelta(days=offset)).date().isoformat()
        if (
            len(days) <= offset
            or not isinstance(days[offset], dict)
            or days[offset].get("date") != day
        ):
            raise ValueError("date_mismatch")
        d = days[offset]
        for code, label, clock, before, after in [
            ("rise", "morning", "sunrise", -45, 60),
            ("set", "evening", "sunset", -90, 45),
        ]:
            event = datetime.fromisoformat(day + "T" + d[clock]).replace(tzinfo=TZ)
            block = d.get(label) or {}
            complete = complete_window(
                fc.get("hourly") or {}, event, before, after, HOURLY.split(",")
            )
            complete = complete and complete_window(
                fc.get("hourly") or {},
                event,
                -180,
                120 if code == "rise" else 30,
                ["precipitation", "precipitation_probability", "weather_code"],
            )
            complete = complete and complete_window(
                air.get("hourly") or {}, event, before, after, ["pm2_5"]
            )
            recent = timedelta(0) <= now - collected < timedelta(minutes=10)
            score = number(block.get("score")) if complete and recent else None
            status = "valid" if score is not None else "unknown" if recent else "stale"
            if event <= now:
                status = "passed"
            m = block.get("metrics") or {}
            results.append(
                dict(
                    source=LOCAL,
                    date=day,
                    event=code,
                    event_time=event.isoformat(),
                    city=city["name"],
                    coordinates=dict(latitude=city["lat"], longitude=city["lon"]),
                    status=status,
                    score=score,
                    quality=None,
                    probability=None,
                    cloud_evidence=dict(
                        mid=number(m.get("cloud_mid")) if complete and recent else None,
                        high=number(m.get("cloud_high"))
                        if complete and recent
                        else None,
                        low=number(m.get("cloud_low")) if complete and recent else None,
                    ),
                    weather=dict(
                        precipitation=m.get("precip_sum")
                        if complete and recent
                        else None,
                        rain_near=m.get("rain_near") if complete and recent else None,
                        rain_early=m.get("rain_early") if complete and recent else None,
                        pop_max=m.get("pop_max") if complete and recent else None,
                    ),
                    freshness=dict(
                        status="recent_acquisition" if recent else "stale",
                        model_cycle_known=False,
                    ),
                    fetched_at=collected.isoformat(),
                    valid_until=(collected + timedelta(minutes=10)).isoformat(),
                    errors=[] if complete else ["missing_hourly_inputs"],
                    path_obstruction=None,
                )
            )
    return results


LOCAL = "追光人本地静态评分"


def instant(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(TZ) if dt.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def number(value, maximum: float = 100):
    return (
        value
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= maximum
        else None
    )


def fresh(value, now):
    end = instant(value)
    return end is not None and now < end


def city_key(city):
    city = city.strip()
    return city[:-1] if city.endswith("市") else city


def resolve_glow_spot(summary, city, day):
    key = city_key(city)
    if len(key) < 2:
        return None
    matches = set()
    for item in summary.get("days", []):
        if item.get("date") != day:
            continue
        # Actual response keeps xihu/waitan outside the spots list.
        cards = list(item.get("spots") or []) + [
            v for v in item.values() if isinstance(v, dict) and v.get("spot")
        ]
        for card in cards:
            name = card.get("spotName") or ""
            alias = {"xihu": "杭州", "waitan": "上海"}.get(card.get("spot"))
            if card.get("date") == day and (
                key == alias or name.startswith(key) or key.lower() == card.get("spot")
            ):
                matches.add(card["spot"])
    return next(iter(matches)) if len(matches) == 1 else None


def resolve_geocode(raw, city):
    key = city_key(city)
    matches = [
        x
        for x in raw.get("results", [])
        if city_key(x.get("name", "")) == key and x.get("country_code") == "CN"
    ]
    ranks = {"PPLC": 0, "PPLA": 1, "PPLA2": 2, "PPLA3": 3}
    if matches:
        best = min(ranks.get(x.get("feature_code"), 4) for x in matches)
        matches = [x for x in matches if ranks.get(x.get("feature_code"), 4) == best]
    if len(matches) != 1:
        raise ValueError("city_not_found_or_ambiguous")
    x = matches[0]
    lat, lon = x.get("latitude"), x.get("longitude")
    if (
        not isinstance(lat, (int, float))
        or not isinstance(lon, (int, float))
        or not -90 <= lat <= 90
        or not -180 <= lon <= 180
    ):
        raise ValueError("invalid_city_coordinates")
    return dict(
        id=str(x.get("id", key)),
        name=x["name"],
        region=x.get("admin1", ""),
        lat=lat,
        lon=lon,
    )


def normalize_glow(raw, day, spot, now):
    p = raw.get("prediction") or {}
    if (
        raw.get("date") != day
        or p.get("date") != day
        or p.get("businessDate") != day
        or p.get("spot") != spot
    ):
        raise ValueError("date_or_city_mismatch")
    acquired = instant(p.get("fetchedAt"))
    if acquired is None or acquired > now + timedelta(minutes=5):
        raise ValueError("invalid_acquisition_time")
    view = dict(p)
    transitions = [
        x
        for x in (p.get("cloudglowTransitions") or [])
        if isinstance(x, dict)
        and instant(x.get("effectiveAt"))
        and instant(x["effectiveAt"]) <= now
    ]
    for transition in sorted(
        transitions, key=lambda x: instant(x["effectiveAt"]) or now
    ):
        view.update(transition)
    freshness = view.get("freshness") or {}
    quality = (
        number(view.get("quality"))
        if freshness.get("quality") == "valid"
        and (view.get("qualityPotential") or {}).get("valueStatus") == "evaluated"
        and fresh(view.get("qualityValidUntil"), now)
        else None
    )
    probability = (
        number(view.get("probability"))
        if freshness.get("probability") == "valid"
        and (view.get("occurrenceEstimate") or {}).get("valueStatus") == "evaluated"
        and fresh(view.get("probabilityValidUntil"), now)
        else None
    )
    event = datetime.fromisoformat(
        day + "T" + (p.get("sunTimes") or {})["sunset"]
    ).replace(tzinfo=TZ)
    status = "valid" if quality is not None or probability is not None else "unknown"
    if not fresh(view.get("qualityValidUntil"), now) and not fresh(
        view.get("probabilityValidUntil"), now
    ):
        status = "stale"
    if event <= now:
        status = "passed"
    metrics = view.get("metrics") or {}
    weather = view.get("weather") or {}
    if quality is None and probability is None:
        # Retain raw evidence only in the raw cache, never display expired cloud/rain.
        metrics, weather = {}, {}
    return dict(
        source=GLOW,
        date=day,
        event="set",
        event_time=event.isoformat(),
        city=p.get("location"),
        spot=spot,
        status=status,
        score=None,
        quality=quality,
        probability=probability,
        probability_calibrated=(view.get("occurrenceEstimate") or {}).get("calibrated"),
        cloud_evidence=dict(
            mid=number(metrics.get("cloudMid")),
            high=number(metrics.get("cloudHigh")),
            low=number(metrics.get("cloudLow")),
        ),
        weather=weather,
        freshness=p.get("freshness"),
        fetched_at=p.get("fetchedAt"),
        quality_valid_until=view.get("qualityValidUntil"),
        probability_valid_until=view.get("probabilityValidUntil"),
        action_valid_until=view.get("actionValidUntil"),
        action_state=view.get("actionState"),
        source_status=view.get("status"),
        errors=[],
        model_cycle_known=False,
    )


def get_json(url, params, timeout):
    request = Request(
        url + "?" + urlencode(params),
        headers={"User-Agent": "MingYiBot-Sky/2.0", "Accept": "application/json"},
    )
    with urlopen(
        request,
        timeout=min(5, max(0.1, timeout)),
        context=ssl.create_default_context(cafile=certifi.where()),
    ) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("response_too_large")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("invalid_source_response")
    return data


def collect_glow(city, now, timeout):
    entries, errors = [], []
    for offset in range(2):
        day = (now + timedelta(days=offset)).date().isoformat()
        try:
            summary = get_json(
                "https://glowsunset.cn/api/home-summary", {"date": day}, timeout
            )
            spot = resolve_glow_spot(summary, city, day)
            if not spot or not isinstance(summary.get("version"), str):
                raise ValueError("unsupported_city_or_date:" + day)
            detail = get_json(
                "https://glowsunset.cn/api/home-detail",
                dict(spot=spot, date=day, version=summary["version"]),
                timeout,
            )
            if detail.get("version") != summary["version"]:
                raise ValueError("version_mismatch")
            normalize_glow(detail, day, spot, now)
            entries.append(dict(day=day, spot=spot, raw=detail))
        except HTTPError as exc:
            errors.append("http_" + str(exc.code))
            if exc.code in (403, 409, 429):
                break
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(str(exc)[:160])
    return dict(
        source=GLOW, collected_at=now.isoformat(), entries=entries, errors=errors
    )


def collect_local(city, now, timeout):
    location = resolve_geocode(
        get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            dict(name=city_key(city), count=10, language="zh", countryCode="CN"),
            timeout,
        ),
        city,
    )
    base = dict(
        latitude=location["lat"],
        longitude=location["lon"],
        timezone="Asia/Shanghai",
        forecast_days=3,
    )
    fc = get_json(
        "https://api.open-meteo.com/v1/forecast",
        dict(base, hourly=HOURLY, current=CURRENT, daily="sunrise,sunset"),
        timeout,
    )
    air = get_json(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        dict(base, hourly="pm2_5,pm10"),
        timeout,
    )
    data = compute_local(location, fc, air, now)
    normalize_local(data, fc, air, location, now, now)
    return dict(
        source=LOCAL,
        collected_at=now.isoformat(),
        city=location,
        forecast=fc,
        air=air,
        result=data,
        errors=[],
    )


def normalize_bundle(bundle, now):
    if bundle.get("source") == GLOW:
        return [
            normalize_glow(x["raw"], x["day"], x["spot"], now)
            for x in bundle.get("entries", [])
        ]
    collected = instant(bundle.get("collected_at"))
    if collected is None:
        raise ValueError("missing_collection_time")
    return normalize_local(
        bundle["result"],
        bundle["forecast"],
        bundle["air"],
        bundle["city"],
        now,
        collected,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Read-only source worker; no QQ/database imports"
    )
    parser.add_argument("source", choices=["glow", "local"])
    parser.add_argument("city")
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    try:
        result = (collect_glow if args.source == "glow" else collect_local)(
            args.city, datetime.now(TZ), args.timeout
        )
    except Exception as exc:
        result = dict(
            source=GLOW if args.source == "glow" else LOCAL,
            errors=[type(exc).__name__ + ": " + str(exc)[:160]],
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
