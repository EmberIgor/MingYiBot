# MingYiBot

基于 NoneBot2 的 QQ 机器人项目，默认使用 OneBot v11 适配器，适合搭配 NapCat、Lagrange 等 QQ 端实现，并通过 Docker 部署到群晖 NAS。

## 本地运行

建议使用 Python 3.11 或 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

启动后，OneBot v11 反向 WebSocket 地址通常配置为：

```text
ws://宿主机IP:8080/onebot/v11/ws
```

如果配置了 `ONEBOT_ACCESS_TOKEN`，QQ 端实现里的 access token 需要保持一致。

## Docker 运行

```bash
cp .env.example .env
docker compose up -d --build
```

默认会把容器内的 `8080` 端口映射到宿主机 `8080`。如果群晖上端口被占用，可以在 `.env` 中修改：

```dotenv
BOT_PORT=18080
```

随后把 NapCat/Lagrange 的反向 WebSocket 地址改为：

```text
ws://群晖IP:18080/onebot/v11/ws
```

## 当前功能

- 基础状态检查：确认机器人在线状态。
- 帮助菜单：快速查看用户可用指令。
- 群聊复读：群内连续出现相同消息达到 2 条时，机器人自动复读一次。
- AI 聊天：在群里 @ 机器人，或私聊机器人时进行 AI 对话；支持切换聊天角色和清空上下文。
- COC7 工具：支持基础骰子、技能检定和快速调查员生成。
- 火烧云查询：查询指定城市今日、明日的日出/日落火烧云分析；支持定时私聊提醒。
- 每日新闻：手动获取 60s 每日新闻图片；支持每天定时向群推送。

## 用户可用命令

命令通常可以在群聊或私聊中使用；其中 AI 聊天在群聊里需要 @ 机器人触发。以下示例里的空格建议保留。

### 基础命令

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.help` | 查看用户可用指令摘要。也可以写作 `.帮助`、`.菜单`，并支持中文句号。 | `.help` |
| `.ping` | 检查机器人是否在线，回复 `pong`。也可以写作 `.状态`。 | `.ping` |

### AI 聊天

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `@机器人 内容` | 与 AI 对话，`@机器人` 可以放在消息任意位置。机器人会按“群/用户/角色”分别保留上下文。 | `@茗懿 帮我想一个跑团导入` |
| `.ai` | 查看当前角色和可用角色。 | `.ai` |
| `.ai 列表` | 查看当前角色和可用角色。 | `.ai 列表` |
| `.ai 角色名` | 切换当前聊天角色，并清空当前角色会话上下文。 | `.ai creative` |
| `.ai 重置` | 清空当前 AI 聊天上下文。 | `.ai 重置` |
| `.ai 重载` | 重新加载角色配置，并恢复为默认角色。 | `.ai 重载` |

默认内置角色包括 `default`、`assistant`、`creative`、`concise`；如果管理员配置了自定义角色，以实际列表为准。
回复或引用某条消息再 @ 机器人时，AI 会同时参考被引用消息；如果被引用消息里有图片，也会一并作为图片输入。

### COC7 骰子与规则

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.r 表达式` | 投掷骰子表达式；不填表达式时默认 `1d100`。支持 `NdM`、常数和加减法。 | `.r 2d6+3` |
| `.ra 技能名 技能值` | COC7 普通检定。技能名可省略，省略时显示为“检定”。 | `.ra 侦查 60` |
| `.coc 数量` | 快速生成 COC7 调查员属性。不填数量时生成 1 名，最多 10 名。 | `.coc3` |

以上以点号开头的命令也支持中文句号，例如 `。r 1d100`、`。coc`。

### 火烧云

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.sun 地点` | 查询指定地点两日内日出、日落时段的火烧云分析。`sun 地点` 裸命令仍可用。 | `.sun 上海` |
| `.火烧云 地点` | `.sun` 的中文写法。`火烧云 地点` 裸命令仍可用。 | `.火烧云 广州` |

地点不填时使用管理员配置的默认城市，当前代码默认值为 `北京`。

### 每日新闻

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.今日新闻` | 获取今日 60s 每日新闻图片。`今日新闻` 裸命令仍可用。 | `.今日新闻` |
如果开启“必须是当天新闻”的检查，而新闻源还没更新，机器人会提示“今日新闻还没有更新，请稍后再试”。如果群聊不在管理员配置的发送范围内，也会提示当前群不可用。

### 自动触发功能

| 功能 | 触发方式 | 说明 |
| --- | --- | --- |
| 群聊复读 | 同一群内连续 2 条相同消息 | 机器人只会在第二条相同消息出现时复读一次，之后同一轮不会反复刷屏。 |
| 每日新闻定时推送 | 默认每天 `08:30` | 推送到允许范围内的群；如果新闻尚未更新，会按配置重试，默认最晚等到 `10:10`。 |
| 火烧云私聊提醒 | 默认每天 `09:00`、`21:00` | 当默认城市的火烧云等级达到阈值时，私聊提醒管理员或配置的接收人。 |

## 管理员配置要点

以下配置可写入 `.env`，NoneBot 会按环境变量读取。变量名通常使用大写形式。

### AI 聊天配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `AICHAT_KEY` | 空 | OpenAI 兼容接口的 API Key。 |
| `AICHAT_BASEURL` | 空 | OpenAI 兼容 Responses API 的 Base URL，例如 `https://api.gptsapi.net/v1`。不要填到 `/responses`。 |
| `AICHAT_MODEL` | 空 | AI 聊天使用的模型名。 |
| `AICHAT_WEB_SEARCH` | `false` | 是否启用 Responses API 的 `web_search` 联网工具。图片解析始终走 Responses API 的 `input_image`。 |
| `AICHAT_DEFAULT_ROLE` | `default` | 默认聊天角色。 |
| `AICHAT_HISTORY_LIMIT` | `12` | 每个会话保留的消息条数，包含 system 消息；裁剪时会保留完整问答轮次。 |
| `AICHAT_ROLES_PATH` | `data/ai_chat_roles.json` | 角色配置文件路径。首次启动会自动生成默认角色文件。 |
| `AICHAT_SESSION_TTL_MINUTES` | `1440` | 会话上下文过期时间，单位分钟。 |

### 每日新闻配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `DAILYNEWS_ENABLED` | `true` | 是否开启每日新闻定时推送。手动命令仍由插件提供。 |
| `DAILYNEWS_TIME` | `08:30` | 每天首次推送时间。 |
| `DAILYNEWS_LATEST_TIME` | `10:10` | 新闻未更新时的最晚重试时间。 |
| `DAILYNEWS_RETRY_INTERVAL_MINUTES` | `10` | 新闻未更新时的重试间隔。 |
| `DAILYNEWS_REQUIRE_TODAY` | `true` | 是否要求新闻源日期必须是今天。 |
| `DAILYNEWS_API_URL` | `https://60s.viki.moe/v2/60s` | 每日新闻接口地址。 |
| `DAILYNEWS_IMAGE_ENCODING` | `image` | 图片编码方式，可选 `image` 或 `image-proxy`。 |
| `DAILYNEWS_GROUP_MODE` | `blacklist` | 群范围模式，可选 `blacklist` 或 `whitelist`。 |
| `DAILYNEWS_GROUP_IDS` | 空列表 | 黑名单或白名单群号列表，取决于 `DAILYNEWS_GROUP_MODE`。 |

### 火烧云配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `SUNSET_API_URL` | `https://sunsetbot.top/` | 火烧云查询接口地址。 |
| `SUNSET_DEFAULT_CITY` | `北京` | 不填写地点时使用的默认城市，也是定时提醒查询城市。 |
| `SUNSET_MODEL` | `GFS` | 查询模型，可选 `GFS` 或 `EC`。 |
| `SUNSET_TIMEOUT_SECONDS` | `10.0` | 请求超时时间。 |
| `SUNSET_NOTIFY_ENABLED` | `true` | 是否开启火烧云定时提醒。 |
| `SUNSET_NOTIFY_TIMES` | `["09:00", "21:00"]` | 每天检查提醒的时间列表。 |
| `SUNSET_NOTIFY_THRESHOLD` | `中烧` | 达到该等级或更高时提醒。 |
| `SUNSET_OWNER_IDS` | 空列表 | 私聊提醒接收人 QQ 号；未配置时使用 NoneBot `SUPERUSERS`。 |

## 目录结构

```text
.
├── bot.py
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── src/plugins
    ├── ai_chat
    ├── coc7
    ├── daily_news
    ├── help
    ├── ping
    ├── repeater
    └── sunset
```

后续插件建议按功能放到 `src/plugins/<插件名>/__init__.py`。
