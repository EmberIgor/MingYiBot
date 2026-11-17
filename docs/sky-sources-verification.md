# 朝晚霞来源实现验证（2026-11-17）

实现完成，本地回归检查通过。**双城实时采集均获得 Glow 今日/明日晚霞，追光人的 Open-Meteo 天气网络请求在本机超时，因此本次未证明追光人实时天气成功；没有伪造该来源的实时值。** Node 原始评分引擎在离线完整/缺失数据契约测试中真实执行并通过。

工作目录：`/Users/weiyige/GitHubProjects/MingYiBot`。执行环境：macOS，隔离 `.venv` 的 CPython 3.13.14。运行依赖来自 `requirements.txt`；Docker 的 Python 3.12/Node 构建与容器执行由 supervisor 独立验收，本实现者未构建、部署或操作任何生产容器。

## 检查范围

编辑前盘点了 `src/plugins/sunset/{__init__,config,data_source}.py`、帮助文本、README/.env.example、运行时城市设置及相关测试。原仓库没有 sunset 专用测试。规范 `docs/BRIEF-sky-sources.md` 与列出的 Hermes 参考文件均未修改。

行为替换、缓存、边界和含糊处的保守解释详见 [来源说明](sky-sources.md)；引擎来源及哈希见 [资产说明](../src/plugins/sunset/assets/README.md)。旧阈值字符串按机会强度使用，默认“中烧”表示各来源独立的 ≥70 强信号，附加云雨/有效期条件，禁止声称已换算为物理烧级。

## 最终本地检查

命令：

```bash
uvx ruff format src/plugins/sunset tests/test_sky_sources.py tests/test_sunset.py
uvx ruff check src/plugins/sunset tests/test_sky_sources.py tests/test_sunset.py --select E4,E7,E9,F,I
INTEGRATION_DB=0 .venv/bin/python -m unittest discover -s tests -v
git diff --check
shasum -a 256 src/plugins/sunset/assets/zhuiguang_scoring.js
```

真实输出：

```text
2 files reformatted, 5 files left unchanged
All checks passed!

----------------------------------------------------------------------
Ran 108 tests in 2.689s

OK (skipped=1)

c5fc3c407a473e2e30ac7bd53fd403be152786a0be3f6a5245c8f4d72539434a  src/plugins/sunset/assets/zhuiguang_scoring.js
```

`git diff --check` 无输出、退出码 0。唯一跳过项是要求专门测试数据库的 opt-in 数据库集成测试；`INTEGRATION_DB=0` 明确禁用它，未连接/写入生产数据库。完整测试输出留在本机 scratch `mingyi-sky/final-tests.txt`，可用上述命令复现。

新增 25 项测试涵盖真实 Glow 响应结构、独立质量/出现估计、null/缺失/过期/未来转换、日期/businessDate/spot/采集时间不一致、城市不存在和同名歧义、原始 Node 引擎、整点缺测与空值不使用上游默认分数、旧采集、一个来源失败后仍展示另一个、缓存逐字段重验证、已过事件和跨来源分钟差异、阈值/非法配置、云/雨门槛、单请求上限、HTTP 429 停源、整轮预算、进程及孙进程超时回收、共享任务取消与并发城市上限，以及原命令和全局城市/北京时间调度。网络与发信边界使用 mocks，未调用真实 QQ 发信。

## 北京、上海实时采集

命令（不导入 NoneBot/QQ/数据库，`alert_preview` 只输出不发送）：

```bash
.venv/bin/python src/plugins/sunset/data_source.py 北京 上海 --json > docs/sky-sources-live.jsonl
```

退出码 0。完整真实 JSON 和文本报告存于 [sky-sources-live.jsonl](sky-sources-live.jsonl)，未做数值替换。

| 城市 | 完成时间（Asia/Shanghai） | 总耗时 | Glow 11-17 质量/出现估计 | Glow 11-18 质量/出现估计 | 追光人实时天气 | 提醒预览 |
| --- | --- | ---: | --- | --- | --- | --- |
| 北京 | 2026-11-17 10:59:45.941076+08:00 | 11.584 s | 54 / 49 | 0 / 0 | TLS 握手超时，未知 | 空字符串 |
| 上海 | 2026-11-17 10:59:57.744128+08:00 | 11.802 s | 75 / 0 | 24 / 6 | TLS 握手超时，未知 | 空字符串 |

Glow 请求实际 spot 是北京 `beijing` 与上海 `waitan`。返回地点分别是“北京 · 东城”“上海 · 黄浦/浦东”，日落时刻分别为 16:56 和 16:54；没有向上海返回北京值。0 是来源明确返回且有效的真实数值；追光人失败保持未知，不填 0。

北京真实文本报告：

```text
【北京】朝晚霞（北京时间）
2026-11-17 朝霞
暂无有效来源，情况未知
2026-11-17 晚霞
Glow Sunset 2026-11-17 16:56：质量潜力 54/100；出现估计 49/100（未校准）；低/中/高云 5.73333/59.8667/41%；有效
2026-11-18 朝霞
暂无有效来源，情况未知
2026-11-18 晚霞
Glow Sunset 2026-11-18 16:56：质量潜力 0/100；出现估计 0/100（未校准）；低/中/高云 0/0/0%；有效
建议：有效证据暂不支持专程出行；未知数据不能当作无霞。
部分来源未知：追光人本地静态评分: URLError: <urlopen error _ssl.c:1015: The handshake operation timed out>
Glow 仅提供晚霞；两源可能共享 Open-Meteo，不能当独立投票或平均。静态评分缺少方向光路验证。
```

上海质量潜力虽为 75，但出现估计为 0，source_status 为 no_opportunity、action_state 为 unavailable，正确阻止了“仅看高质量分就提醒”。北京质量 54 未达到默认强信号门槛。没有 QQ 通知。

## 网络阻塞与实际地理编码

初次实跑发现同名城市和村庄并列，已用真实结构回归并修复行政城市选择。只读地理编码实测成功返回：

| 查询 | 选定结果 | 经纬度 | feature_code | 同名项 |
| --- | --- | --- | --- | --- |
| 北京 | 北京（北京市） | 39.9075, 116.39723 | PPLC | 另有重庆、四川的同名 PPL 村庄 |
| 上海 | 上海（上海市） | 31.22222, 121.45806 | PPLA | 另有浙江、云南等同名 PPL，及 ISL 项 |

天气端点随后在 5 秒请求时限内失败；独立核查命令：

```bash
curl --max-time 5 -sS -w '\nhttp=%{http_code} connect=%{time_connect} tls=%{time_appconnect} total=%{time_total}\n' 'https://api.open-meteo.com/v1/forecast?latitude=39.9075&longitude=116.39723&timezone=Asia%2FShanghai&forecast_days=3&daily=sunrise,sunset'
dscacheutil -q host -a name api.open-meteo.com
curl --max-time 5 -sS 'https://dns.google/resolve?name=api.open-meteo.com&type=A'
curl --resolve api.open-meteo.com:443:51.81.167.44 --max-time 5 -sS -w '\nhttp=%{http_code} total=%{time_total}\n' 'https://api.open-meteo.com/v1/forecast?latitude=39.9075&longitude=116.39723&timezone=Asia%2FShanghai&forecast_days=3&daily=sunrise,sunset'
```

真实输出摘录：

```text
curl: (28) Connection timed out after 5012 milliseconds
http=000 connect=0.000000 tls=0.000000 total=5.012532

name: api.open-meteo.com
ip_address: 198.18.1.7

Google DNS Answer: api.open-meteo.com. A 51.81.167.44

curl: (28) Connection timed out after 5004 milliseconds
http=000 total=5.004371
```

独立 `--resolve` 仅影响该次 curl，没有更改 DNS、代理或代码，也没有关闭 TLS 校验。这证明本次网络路径未连通，不证明 Open-Meteo 服务全局不可用。由于 forecast 失败后立即停止该来源，最终双城采集未继续请求 air-quality；没有声称其这次在线状态正常。supervisor 应从最终镜像/运行环境重复双城只读命令，补充追光人实时成功证据后再决定部署。

## Supervisor 独立验收

2026-11-17 11:07 再跑 `.venv/bin/python -m unittest discover -s tests`：108 tests in 2.632s，OK (skipped=1)。检查了来源身份/有效期、缺失处理、云雨门槛和已过事件过滤。

网络已恢复；本机实跑北京/上海分别 9.355s / 9.100s，两源均成功，原始输出在 `sky-sources-parent-live.jsonl`。北京今日追光人朝/晚指数77/79（朝霞已过）、明日39/42；上海51/69、54/51。数值与 Glow 独立保留，没有平均。

`docker build --build-arg MINGYI_VERSION=sky-sources-20261117 -t mingyibot:sky-sources-20261117 .` 成功。随后以无生产挂载、无凭据、无 QQ 连接的临时容器运行 `python src/plugins/sunset/data_source.py 北京 上海 --json`，9.296s / 9.544s，两源成功、errors均为空。容器内 Node 实际计算成功；北京提醒预览仅今日晚霞，上海提醒预览为空。`--rm` 容器退出即清除。

## 交付边界

无 commit/push/deploy，无生产容器/远端主机/数据库写入，无 QQ 消息，无生产挂载路径访问或修改。运行时仅使用仓库内自包含代码与引擎；源站请求固定、串行、不重试、每源 18 秒进程组预算、整轮 39 秒。尚待 supervisor 完成 Docker 构建/容器运行、独立代码复核及网络恢复后的追光人实时验收。上游 JS 未附许可声明，来源说明已记录此事实，不宣称特定开源许可证。
