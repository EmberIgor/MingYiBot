/**
 * 火烧云评分引擎 · JS 端口（静态回退模式使用）
 * 与 lib/HuoShaoYun.php + lib/Forecast.php 保持完全一致的算法与输出结构
 */
window.HSY = (function () {
  'use strict';

  /**
   * 取样窗口（分钟，相对日出/日落时刻）
   * 霞光只发生在太阳高度角约 -6°~+5° 的时段（中纬度约 50-70 分钟），
   * 原先取 3.5~4 小时会把白天/夜间的云况平均进来，稀释真实信号。
   * 仍放宽到 1.5~2 小时，是因为 Open-Meteo 只提供整点值，窗口太窄会只剩 1 个样本。
   */
  var WINDOW = { evening: [-90, 45], morning: [-45, 60] };

  /* 降水检测窗口：比云况窗口宽，雨云系的影响会延续到雨后 */
  var RAIN_WINDOW = { evening: [-180, 30], morning: [-180, 120] };

  /* 实况修正权重：距事件时刻越近，当前实况越能代表那时的天空（已发生的不修正） */
  var OBS_WEIGHT = [[30, 0.60], [90, 0.45], [180, 0.25], [240, 0.10]];

  /* boost：实况明确恶劣（正在下雨/起雾）时放大权重，模式此时不可信 */
  function obsWeight(eventTs, nowTs, boost) {
    var dt = (eventTs - nowTs) / 60000;
    if (dt <= 0) return 0;
    var f = boost || 1;
    for (var i = 0; i < OBS_WEIGHT.length; i++) {
      if (dt <= OBS_WEIGHT[i][0]) return Math.min(0.85, OBS_WEIGHT[i][1] * f);
    }
    return 0;
  }

  /* 用当前实况重算分数：云量/云层/湿度/能见度/是否降水取实况，其余沿用预报 */
  function obsScore(current, m) {
    var mc = {}, k;
    for (k in m) mc[k] = m[k];
    var map = { cloud: 'cloud_cover', cloud_low: 'cloud_cover_low', cloud_mid: 'cloud_cover_mid', cloud_high: 'cloud_cover_high', rh: 'relative_humidity_2m' };
    var hit = false;
    for (k in map) {
      if (current[map[k]] !== undefined && isFinite(current[map[k]])) { mc[k] = current[map[k]]; hit = true; }
    }
    if (current.visibility !== undefined && isFinite(current.visibility)) { mc.vis_km = current.visibility / 1000; hit = true; }
    var raining = false;
    if (current.precipitation !== undefined && isFinite(current.precipitation) && current.precipitation > 0) raining = true;
    if (current.weather_code !== undefined) {
      var c = +current.weather_code;
      if ((c >= 51 && c <= 99) || c === 45 || c === 48) raining = true;
    }
    if (raining) { mc.rain_near = 1; hit = true; }
    if (!hit) return null;
    return score(mc).score;
  }

  /** 加权半衰（分钟）：距事件时刻越近权重越高 */
  var W_HALFLIFE_MIN = 45;

  function wOf(t, eventTs) {
    return 1 / (1 + Math.abs(t - eventTs) / (W_HALFLIFE_MIN * 60000));
  }

  /** 分段线性插值 */
  function piecewise(points, x) {
    var n = points.length;
    if (x <= points[0][0]) return points[0][1];
    if (x >= points[n - 1][0]) return points[n - 1][1];
    for (var i = 1; i < n; i++) {
      if (x <= points[i][0]) {
        var x0 = points[i - 1][0], y0 = points[i - 1][1];
        var x1 = points[i][0], y1 = points[i][1];
        if (x1 === x0) return y1;
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
      }
    }
    return points[n - 1][1];
  }

  /** 火烧云指数 0-100 */
  function score(m) {
    var parts = {};
    parts.cloud = piecewise([[0, 0], [15, 5], [35, 13], [50, 17], [65, 20], [80, 17], [90, 9], [100, 0]], m.cloud);
    var mid = piecewise([[0, 0], [10, 10], [30, 26], [50, 30], [70, 30], [85, 24], [100, 10]], m.cloud_mid);
    var low = piecewise([[0, 0], [25, 0], [45, -4], [65, -10], [100, -16]], m.cloud_low);
    var high = piecewise([[0, 0], [10, 3], [30, 6], [60, 6], [85, 0], [100, -4]], m.cloud_high);
    parts.structure = Math.max(0, Math.min(30, mid + low + high));
    // 高湿但能见度差 = 霾/雾，不是"云体明亮"，按能见度封顶
    parts.humidity = Math.min(
      piecewise([[20, 4], [35, 8], [50, 11], [65, 15], [80, 15], [92, 9], [100, 3]], m.rh),
      piecewise([[3, 6], [8, 9], [15, 13], [25, 15]], m.vis_km)
    );
    parts.visibility = piecewise([[0.5, 0], [2, 2], [5, 4], [10, 6], [16, 8], [25, 10], [40, 10]], m.vis_km);
    // 气溶胶峰值由 45-75 下调到 20-35 μg/m³：前者对应能见度仅 5-10 km，
    // 与「能见度 25km 满分」自相矛盾；适度气溶胶才加深红橙，过量只会衰减颜色
    if (m.pm25 === null || m.pm25 === undefined || !isFinite(m.pm25)) {
      parts.aerosol = 11;
    } else {
      parts.aerosol = piecewise([[0, 5], [10, 9], [20, 13], [35, 15], [50, 11], [75, 7], [100, 4], [150, 2], [250, 1]], m.pm25);
    }
    // 能见度上限：大气浑浊时气溶胶已是过量而非适度
    parts.aerosol = Math.min(
      parts.aerosol,
      piecewise([[2, 3], [5, 5], [10, 8], [16, 12], [25, 15]], m.vis_km)
    );
    parts.wind = piecewise([[0, 10], [8, 10], [15, 8], [25, 6], [35, 3], [50, 1]], m.wind);

    var total = 0, k;
    for (k in parts) total += parts[k];

    /* 降水 / 天气现象修正：霞光时段内的天气代码 > 累计降水 > 最大降水概率
       旧逻辑只看窗口均值，短时阵雨被平均稀释后几乎不触发 */
    var factor = 1;
    var precipSum = (m.precip_sum !== undefined && m.precip_sum !== null) ? m.precip_sum : (m.precip || 0);
    var precipNear = (m.precip_near !== undefined && m.precip_near !== null) ? m.precip_near : precipSum;
    var popMax = (m.pop_max !== undefined && m.pop_max !== null) ? m.pop_max : (m.pop || 0);
    if (m.rain_near) factor *= 0.42;
    else if (precipNear > 0.5) factor *= 0.60;
    else if (precipNear > 0.1) factor *= 0.80;
    if (m.rain_early) factor *= 0.85;
    if (popMax >= 70) factor *= 0.80;
    else if (popMax >= 40) factor *= 0.90;
    total *= factor;

    // 光路修正：太阳那一侧地平线被低云堵死时，本地云再好也照不亮
    // （浏览器直连模式拿不到上游坐标，path_occ 为 null → 中性不修正）
    var pathFactor = 1;
    if (typeof m.path_occ === 'number' && isFinite(m.path_occ)) {
      pathFactor = piecewise([[0, 1], [20, 1], [45, 0.86], [70, 0.72], [100, 0.58]], m.path_occ);
      total *= pathFactor;
    }

    var s = Math.round(total);
    s = Math.max(0, Math.min(100, s));
    return { score: s, parts: parts, factor: Math.round(factor * 100) / 100, path_factor: Math.round(pathFactor * 100) / 100 };
  }

  /** 等级 */
  function grade(s, type) {
    var m = type === 'morning' ? '朝霞' : '晚霞';
    if (s >= 85) return ['S', '爆彩', '#ff2d55', '世纪级' + m + '，值得定好闹钟守候'];
    if (s >= 70) return ['A', '极佳', '#ff6b35', '大片' + m + '烧红天际，出门抬头就有惊喜'];
    if (s >= 55) return ['B', '优良', '#ffa940', '值得守候的' + m + '，建议到视野开阔处'];
    if (s >= 40) return ['C', '一般', '#ffd666', '天空略有颜色，期望不必太高'];
    if (s >= 25) return ['D', '较差', '#95de64', '基本无彩，看看就好'];
    return ['E', '无彩', '#7dd3fc', '天空大概率平淡，早点回家'];
  }

  /** 观赏窗口 */
  function viewingAdvice(eventIso, type) {
    var t = ts(eventIso);
    if (t === null) return { start: '--:--', end: '--:--' };
    var start, end;
    if (type === 'evening') { start = t - 40 * 60000; end = t + 30 * 60000; }
    else { start = t - 30 * 60000; end = t + 40 * 60000; }
    return { start: hhmm(start), end: hhmm(end) };
  }

  /** 民间谚语 */
  function proverb(eveningScore, morningScore) {
    if (eveningScore >= 55) return '晚霞行千里 —— 谚语预示未来 1-2 天天气转好';
    if (morningScore >= 55) return '朝霞不出门 —— 谚语提示西方有降水系统靠近';
    return null;
  }

  // ---------- 内部工具 ----------
  function ts(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '');
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]).getTime();
  }
  function hhmm(t) {
    var d = new Date(t);
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }
  function r1(v) { return v === null ? null : Math.round(v * 10) / 10; }

  function avgHourly(hourly, v, start, end, eventTs) {
    if (!hourly || !hourly[v]) return null;
    var times = hourly.time || [], vals = hourly[v], sum = 0, wsum = 0;
    for (var i = 0; i < times.length; i++) {
      var t = ts(times[i]);
      if (t === null || t < start || t > end) continue;
      var x = vals[i];
      if (typeof x !== 'number' || !isFinite(x)) continue;
      var w = (eventTs === null || eventTs === undefined) ? 1 : wOf(t, eventTs);
      sum += x * w; wsum += w;
    }
    return wsum > 0 ? sum / wsum : null;
  }

  function sumHourly(hourly, v, start, end) {
    if (!hourly || !hourly[v]) return null;
    var times = hourly.time || [], vals = hourly[v], sum = 0, n = 0;
    for (var i = 0; i < times.length; i++) {
      var t = ts(times[i]);
      if (t === null || t < start || t > end) continue;
      var x = vals[i];
      if (typeof x === 'number' && isFinite(x)) { sum += x; n++; }
    }
    return n > 0 ? sum : null;
  }

  /* 降水概率是"该小时会发生"的概率，取平均会把短时阵雨稀释掉，故取最大 */
  function maxHourly(hourly, v, start, end) {
    if (!hourly || !hourly[v]) return null;
    var times = hourly.time || [], vals = hourly[v], mx = null;
    for (var i = 0; i < times.length; i++) {
      var t = ts(times[i]);
      if (t === null || t < start || t > end) continue;
      var x = vals[i];
      if (typeof x === 'number' && isFinite(x) && (mx === null || x > mx)) mx = x;
    }
    return mx;
  }

  /* 窗口内是否出现挡光天气：51-99 雨/雪/阵雨/雷暴，45/48 雾 */
  function hasRainCode(hourly, start, end) {
    if (!hourly || !hourly.weather_code) return false;
    var times = hourly.time || [], vals = hourly.weather_code;
    for (var i = 0; i < times.length; i++) {
      var t = ts(times[i]);
      if (t === null || t < start || t > end) continue;
      var c = vals[i];
      if (typeof c === 'number' && ((c >= 51 && c <= 99) || c === 45 || c === 48)) return true;
    }
    return false;
  }

  function modeCode(hourly, start, end, eventTs) {
    if (!hourly || !hourly.weather_code) return null;
    var times = hourly.time || [], vals = hourly.weather_code, counts = {};
    for (var i = 0; i < times.length; i++) {
      var t = ts(times[i]);
      if (t === null || t < start || t > end) continue;
      var v = vals[i];
      if (typeof v === 'number') {
        var w = (eventTs === null || eventTs === undefined) ? 1 : wOf(t, eventTs);
        counts[v] = (counts[v] || 0) + w;
      }
    }
    var best = null, bc = -1;
    for (var k in counts) { if (counts[k] > bc) { bc = counts[k]; best = +k; } }
    return best;
  }

  /** 窗口内风向矢量平均（气象角度：0=北，90=东，即风的来向；传 eventTs 时加权） */
  function vectorWind(hourly, start, end, eventTs) {
    if (!hourly || !hourly.wind_direction_10m || !hourly.wind_speed_10m) return null;
    var times = hourly.time || [], dirs = hourly.wind_direction_10m, spds = hourly.wind_speed_10m;
    var u = 0, v = 0, n = 0;
    for (var i = 0; i < times.length; i++) {
      var t = ts(times[i]);
      if (t === null || t < start || t > end) continue;
      var d = dirs[i], s = spds[i];
      if (typeof d !== 'number' || typeof s !== 'number') continue;
      var w = (eventTs === null || eventTs === undefined) ? 1 : wOf(t, eventTs);
      var r = d * Math.PI / 180;
      u += -Math.sin(r) * s * w;
      v += -Math.cos(r) * s * w;
      n++;
    }
    if (n === 0) return null;
    var dir = Math.atan2(-u, -v) * 180 / Math.PI;
    if (dir < 0) dir += 360;
    return dir;
  }

  var WMO = {
    0: '晴', 1: '大部晴朗', 2: '局部多云', 3: '多云', 45: '雾', 48: '冻雾',
    51: '毛毛雨', 53: '毛毛雨', 55: '浓毛毛雨', 56: '冻毛毛雨', 57: '冻毛毛雨',
    61: '小雨', 63: '中雨', 65: '大雨', 66: '冻雨', 67: '冻雨',
    71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒',
    80: '阵雨', 81: '强阵雨', 82: '暴雨', 85: '阵雪', 86: '强阵雪',
    95: '雷阵雨', 96: '雷阵雨伴冰雹', 99: '强雷雨伴冰雹'
  };
  function weatherLabel(c) { return c === null ? '多云' : (WMO[c] || '多云'); }

  /**
   * 光路遮挡度 0-100（100 = 太阳方向被云完全堵死）
   * 浏览器直连模式拿不到额外的上游坐标，此处恒为 null，评分侧按中性处理
   */
  function pathObstruction(pathFcs, eventTs, type) {
    if (!pathFcs) return null;
    return null;
  }

  /**
   * 组装晚霞/朝霞评分块
   * pathFcs 为光路采样点数据；浏览器直连模式拿不到额外坐标，传 null 时光路项按中性处理
   */
  function block(hourly, aqHourly, eventIso, type, pathFcs, current) {
    var t = ts(eventIso);
    if (t === null) return { error: 'bad-event-time' };
    var win = WINDOW[type] || WINDOW.evening;
    var start = t + win[0] * 60000;
    var end = t + win[1] * 60000;

    function f(v, d) { var x = avgHourly(hourly, v, start, end, t); return x === null ? d : x; }
    var visM = avgHourly(hourly, 'visibility', start, end, t);
    var pm25 = avgHourly(aqHourly, 'pm2_5', start, end, t);
    var wdir = vectorWind(hourly, start, end, t);

    /* 降水 / 天气现象：宽窗口取累计与最大值，并按临近、前期分开 */
    var rw = RAIN_WINDOW[type] || RAIN_WINDOW.evening;
    var rStart = t + rw[0] * 60000, rEnd = t + rw[1] * 60000;
    var precipSum = sumHourly(hourly, 'precipitation', rStart, rEnd);
    var precipNear = sumHourly(hourly, 'precipitation', start, end);
    var popMax = maxHourly(hourly, 'precipitation_probability', rStart, rEnd);
    var rainNear = hasRainCode(hourly, start, end);
    var rainEarly = rStart < start ? hasRainCode(hourly, rStart, start) : false;

    var metrics = {
      cloud: r1(f('cloud_cover', 50)),
      cloud_low: r1(f('cloud_cover_low', 20)),
      cloud_mid: r1(f('cloud_cover_mid', 20)),
      cloud_high: r1(f('cloud_cover_high', 20)),
      rh: r1(f('relative_humidity_2m', 60)),
      vis_km: r1(visM === null ? 20 : visM / 1000),
      wind: r1(f('wind_speed_10m', 10)),
      wind_dir: wdir === null ? null : Math.round(wdir),
      pm25: pm25 === null ? null : r1(pm25),
      precip: Math.round(f('precipitation', 0) * 100) / 100,
      pop: Math.round(f('precipitation_probability', 0)),
      precip_sum: Math.round((precipSum === null ? 0 : precipSum) * 100) / 100,
      precip_near: Math.round((precipNear === null ? 0 : precipNear) * 100) / 100,
      pop_max: popMax === null ? 0 : Math.round(popMax),
      rain_near: rainNear ? 1 : 0,
      rain_early: rainEarly ? 1 : 0,
      path_occ: pathObstruction(pathFcs, t, type)
    };

    var res = score(metrics);
    var scoreFx = res.score;
    var obs = null;
    if (current) {
      var w = obsWeight(t, Date.now(), current.rain_flag ? 1.25 : 1);
      if (w > 0) {
        var os = obsScore(current, metrics);
        if (os !== null) {
          scoreFx = Math.max(0, Math.min(100, Math.round(scoreFx * (1 - w) + os * w)));
          obs = { weight: w, score: Math.round(os) };
        }
      }
    }
    var g = grade(scoreFx, type);
    var win = viewingAdvice(eventIso, type);
    var code = modeCode(hourly, start, end, t);
    var partsOut = {};
    for (var k in res.parts) partsOut[k] = Math.round(res.parts[k] * 10) / 10;

    return {
      score: scoreFx, obs: obs, grade: g[0], gradeLabel: g[1], color: g[2], advice: g[3],
      window: win, weather: weatherLabel(code), weatherCode: code,
      metrics: metrics, parts: partsOut, factor: res.factor, path_factor: res.path_factor
    };
  }

  /** 组装某一天的完整预报块（朝霞 + 晚霞）；无当天数据返回 null */
  function dayForecast(fc, aqHourly, date, paths, current) {
    var idx = fc.daily.time.indexOf(date);
    if (idx === -1) return null;
    var sunrise = fc.daily.sunrise && fc.daily.sunrise[idx];
    var sunset = fc.daily.sunset && fc.daily.sunset[idx];
    if (!sunrise || !sunset) return null;
    var hourly = fc.hourly || {};
    var evening = block(hourly, aqHourly, sunset, 'evening', paths && paths.evening, current);
    var morning = block(hourly, aqHourly, sunrise, 'morning', paths && paths.morning, current);
    return {
      date: date,
      sunrise: sunrise.slice(11, 16),
      sunset: sunset.slice(11, 16),
      evening: evening, morning: morning,
      proverb: proverb(evening.score, morning.score)
    };
  }

  /** 计算单城市预报：today（今天）+ days（明天/后天，原有模块） */
  function computeCity(city, fc, aq) {
    var out = {
      id: city.id, name: city.name, region: city.region,
      lat: city.lat, lon: city.lon, error: null, today: null, days: []
    };
    if (!fc || !fc.daily || !fc.daily.time) { out.error = 'forecast-unavailable'; return out; }
    var hourly = fc.hourly || {};
    var aqHourly = (aq && aq.hourly) ? aq.hourly : {};
    var today = todayInTZ('Asia/Shanghai');
    // 实况只修正今天：明天后天的天空与现在无关
    var current = (fc && fc.current && typeof fc.current === 'object') ? fc.current : null;

    out.today = dayForecast(fc, aqHourly, dateStr(today), [], current);

    for (var d = 1; d <= 2; d++) {
      var day = dayForecast(fc, aqHourly, dateStr(new Date(today.getTime() + d * 86400000)));
      if (day === null) continue;
      out.days.push(day);
    }
    if (!out.days.length) out.error = 'no-days';
    return out;
  }

  /** Date → 'YYYY-MM-DD'（按本地墙上时间） */
  function dateStr(dt) {
    return dt.getFullYear() + '-' + ('0' + (dt.getMonth() + 1)).slice(-2) + '-' + ('0' + dt.getDate()).slice(-2);
  }

  /** 指定时区的"今天"（按墙上时间） */
  function todayInTZ(tz) {
    var now = new Date();
    var inv = new Date(now.toLocaleString('en-US', { timeZone: tz }));
    inv.setHours(0, 0, 0, 0);
    return inv;
  }

  return {
    piecewise: piecewise, score: score, grade: grade,
    viewingAdvice: viewingAdvice, proverb: proverb, computeCity: computeCity,
    todayInTZ: todayInTZ, weatherLabel: weatherLabel
  };
})();
