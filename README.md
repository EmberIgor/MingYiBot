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
- 群聊复读：群内连续出现相同消息达到 2 条时，机器人自动复读一次。
- AI 聊天：在群里 @ 机器人，或私聊机器人时进行 AI 对话；支持切换聊天角色和清空上下文。
- COC7 工具：支持基础骰子、技能检定、奖励骰/惩罚骰、理智检定、快速调查员生成和 COC7 规则问答。
- 火烧云查询：查询指定城市今日、明日的日出/日落火烧云分析；支持定时私聊提醒。
- 每日新闻：手动获取 60s 每日新闻图片；支持每天定时向群推送。

## 用户可用命令

命令通常可以在群聊或私聊中使用；其中 AI 聊天在群聊里需要 @ 机器人触发。以下示例里的空格建议保留。

### 基础命令

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `/ping` | 检查机器人是否在线，回复 `pong`。 | `/ping` |
| `状态` | `/ping` 的别名。 | `状态` |

### AI 聊天

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `@机器人 内容` | 与 AI 对话，可附带图片。机器人会按“群/用户/角色”分别保留上下文。 | `@茗懿 帮我想一个跑团导入` |
| `/ai角色` | 查看当前角色和可用角色。 | `/ai角色` |
| `/ai角色 列表` | 查看当前角色和可用角色。 | `/ai角色 列表` |
| `/ai角色 角色名` | 切换当前聊天角色，并清空当前角色会话上下文。 | `/ai角色 creative` |
| `/ai角色 重置` | 清空当前 AI 聊天上下文。 | `/ai角色 重置` |
| `/ai角色 重载` | 重新加载角色配置，并恢复为默认角色。 | `/ai角色 重载` |

`/ai角色` 也可以写作 `聊天角色` 或 `角色`。默认内置角色包括 `default`、`assistant`、`creative`、`concise`；如果管理员配置了自定义角色，以实际列表为准。

### COC7 骰子与规则

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.r 表达式` | 投掷骰子表达式；不填表达式时默认 `1d100`。支持 `NdM`、常数和加减法。 | `.r 2d6+3` |
| `.ra 技能名 技能值` | COC7 普通检定。技能名可省略，省略时显示为“检定”。 | `.ra 侦查 60` |
| `.rb 技能名 技能值` | COC7 奖励骰检定。 | `.rb 聆听 50` |
| `.rp 技能名 技能值` | COC7 惩罚骰检定。 | `.rp 图书馆 70` |
| `.sc 当前理智/成功损失/失败损失` | 理智检定并计算 SAN 损失。损失值可以是固定数值或骰子表达式。 | `.sc 60/1/1d6` |
| `.coc` | 快速生成一名 COC7 调查员属性。 | `.coc` |
| `/coc 问题` | 向 COC7 AI 规则助手提问。 | `/coc 奖励骰怎么判定？` |

以上以点号开头的命令也支持中文句号，例如 `。r 1d100`、`。coc`。

### 火烧云

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `/sun 地点` | 查询指定地点两日内日出、日落时段的火烧云分析。 | `/sun 上海` |
| `sun 地点` | `/sun` 的无斜杠写法。 | `sun 北京` |
| `火烧云 地点` | `/sun` 的中文别名。 | `火烧云 广州` |

地点不填时使用管理员配置的默认城市，当前代码默认值为 `北京`。

### 每日新闻

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `/今日新闻` | 获取今日 60s 每日新闻图片。 | `/今日新闻` |
| `今日新闻` | 无斜杠写法。 | `今日新闻` |
| `每日新闻` | `/今日新闻` 的别名。 | `每日新闻` |
| `60s` | `/今日新闻` 的别名。 | `60s` |

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
| `AICHAT_KEY` | 空 | OpenAI 兼容接口的 API Key。使用 V-API 时填写令牌管理中的 Token。 |
| `AICHAT_BASEURL` | 空 | OpenAI 兼容接口 Base URL。使用 V-API 时填写 `https://api.gpt.ge/v1`。 |
| `AICHAT_MODEL` | 空 | AI 聊天使用的模型名；图片聊天需要选择支持图像分析的模型，例如 `gpt-4o`。 |
| `AICHAT_DEFAULT_ROLE` | `default` | 默认聊天角色。 |
| `AICHAT_HISTORY_LIMIT` | `12` | 每个会话保留的消息条数，包含 system 消息。 |
| `AICHAT_IMAGE_MODE` | `url` | 图片发送方式。`url` 直接传 OneBot 图片 URL；`base64` 会先下载图片并转成 data URL，兼容无法访问 QQ 临时图的上游。 |
| `AICHAT_IMAGE_MAX_BYTES` | `5242880` | `base64` 模式下允许下载的单张图片最大字节数。 |
| `AICHAT_WEB_SEARCH_ENABLED` | `false` | 是否通过 Responses API 开启火山方舟 Web Search 联网搜索工具。 |
| `AICHAT_WEB_SEARCH_MAX_TOOL_CALLS` | `1` | 联网搜索工具最多调用轮数；设为 `0` 表示不传限制。 |
| `AICHAT_ROLES_PATH` | `data/ai_chat_roles.json` | 角色配置文件路径。首次启动会自动生成默认角色文件。 |
| `AICHAT_SESSION_TTL_MINUTES` | `1440` | 会话上下文过期时间，单位分钟。 |

图片聊天会按 OpenAI 多模态 `image_url` 内容块发送给模型；请把 `AICHAT_MODEL` 配成支持视觉输入的模型。如果上游 OpenAI 兼容服务无法访问 QQ 图片临时 URL，可以把 `AICHAT_IMAGE_MODE` 改成 `base64`。

火山方舟 Web Search 需要先在火山控制台开通/授权联网内容插件，然后配置 `AICHAT_BASEURL=https://ark.cn-beijing.volces.com/api/v3`、火山方舟模型名和 `AICHAT_WEB_SEARCH_ENABLED=true`。开关打开后，AI 聊天会改走 Responses API 并传入 `web_search` 工具；未开启时仍使用普通 Chat Completions。

### COC7 AI 规则助手配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `COC7_AI_KEY` | 空 | COC7 规则助手 API Key。未配置时会尝试复用 `AICHAT_KEY`。 |
| `COC7_AI_BASEURL` | 空 | COC7 规则助手 Base URL。未配置时会尝试复用 `AICHAT_BASEURL`。 |
| `COC7_AI_MODEL` | 空 | COC7 规则助手模型名。未配置时会尝试复用 `AICHAT_MODEL`。 |

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
    ├── ping
    ├── repeater
    └── sunset
```

后续插件建议按功能放到 `src/plugins/<插件名>/__init__.py`。
