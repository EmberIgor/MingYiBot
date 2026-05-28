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

## Docker 本地运行

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

## 群晖自动部署

生产环境推荐使用 GitHub Actions 构建镜像并推送到 GHCR，群晖只负责拉取新镜像和重启容器。这样每次 `git push` 到 `main` 后，不需要在 Container Manager 里删除项目再重建。

如果只使用群晖 Container Manager 图形界面，优先选择 `synology` 子目录创建项目。Container Manager 会自动使用该目录内的 `docker-compose.yml`，这个文件已经把机器人和 Watchtower 放在同一个项目里。

### 1. GitHub Actions

仓库内的 `.github/workflows/docker-image.yml` 会在 `main` 分支 push 或手动触发时构建镜像，并推送：

```text
ghcr.io/emberigor/mingyibot:latest
ghcr.io/emberigor/mingyibot:<commit-sha>
```

`latest` 用于日常自动更新，提交 SHA tag 用于回滚。

### 2. 群晖首次部署

在群晖项目根目录准备 `.env`，也就是 `.env.example` 所在目录：

```bash
cp .env.example .env
```

如果使用 Container Manager 并把项目路径选为 `synology` 子目录，`.env` 仍然放在 `synology` 的上一级：

```text
/volume1/docker/MingYiBot/.env
/volume1/docker/MingYiBot/synology/docker-compose.yml
```

`synology/docker-compose.yml` 会通过 `env_file: ../.env` 把配置注入容器，并把同一份文件只读挂载到容器内的 `/app/.env`。这样即使群晖 Container Manager 没有正确处理 `env_file`，NoneBot 启动时也能直接读取 `/app/.env`。不要只依赖 `environment` 里的 `${变量:-}` 插值；在部分群晖 Container Manager 场景下，插值阶段读不到 `.env` 时会把这些值展开成空字符串。

如果 GHCR 镜像是私有的，先在群晖 SSH 中登录 GHCR。这个 token 只需要 GitHub `read:packages` 权限，用于首次手动 `pull`：

```bash
docker login ghcr.io
```

然后启动生产容器：

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

如果使用 Container Manager：

1. 打开 Container Manager。
2. 进入“项目”。
3. 选择“新增”。
4. 项目名称填写 `mingyibot`。
5. 路径选择本仓库里的 `synology` 子目录，例如 `/volume1/docker/MingYiBot/synology`。
6. 使用该目录现有的 `docker-compose.yml` 创建项目。
7. 在 `synology` 的上一级准备 `.env`，内容按 `.env.example` 填写；如果镜像是私有的，额外填写 `GHCR_USERNAME` 和 `GHCR_PAT`。如果使用 `synology/docker-compose.yml` 内置的 Watchtower，还需要把同一组凭据写入 `REPO_USER` 和 `REPO_PASS`。
8. 创建并启动项目。

### 3. 自动拉取新镜像

启动 Watchtower 后，它会只更新带有 Watchtower 标签的 `mingyi-bot` 容器，默认每 300 秒检查一次：

```bash
docker compose -f docker-compose.watchtower.yml up -d
```

如果 GHCR 镜像是私有的，还需要让 Watchtower 自己带上拉取凭据。在 `.env` 中填写：

```dotenv
GHCR_USERNAME=你的GitHub用户名
GHCR_PAT=只包含read:packages权限的GitHub PAT
```

然后用 override 启动：

```bash
docker compose -f docker-compose.watchtower.yml -f docker-compose.watchtower.private.yml up -d
```

如需调整检查间隔，可以在 `.env` 中设置：

```dotenv
WATCHTOWER_POLL_INTERVAL=600
```

### 4. 日常更新和配置变更

只改机器人代码时，把代码推送到 `main`，等待 GitHub Actions 构建成功和 Watchtower 自动拉取即可。

如果本次更新涉及以下内容，Watchtower 不会自动应用，需要在群晖 Container Manager 中手动重启/重建项目：

- `docker-compose.yml`、`synology/docker-compose.yml` 等 Compose 文件。
- `.env` 中的配置项。
- 端口、挂载目录、`env_file`、`volumes`、`environment`、网络等容器配置。
- `data/` 下已经持久化的运行时配置，例如 `data/ai_chat_roles.json`。

如果使用 SSH，也可以在 `synology` 目录执行：

```bash
docker compose pull
docker compose up -d --force-recreate
```

### 5. 回滚

如果要回滚，把 `docker-compose.prod.yml` 里的镜像 tag 从 `latest` 临时改成某个历史提交 SHA tag，然后执行：

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
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
| `.ai 角色名` | 切换当前聊天角色，并清空当前角色会话上下文。 | `.ai jarvis` |
| `.ai 重置` | 清空当前 AI 聊天上下文。 | `.ai 重置` |
| `.ai 重载` | 重新加载角色配置，并恢复为默认角色。 | `.ai 重载` |
| `.ai 记忆` | 查看当前用户的长期记忆。长期记忆按 QQ 用户保存，跨群聊和私聊共享。 | `.ai 记忆` |
| `.ai 记住 内容` | 手动保存一条长期记忆，立即生效，不额外调用模型。 | `.ai 记住 我喜欢简洁一点的回答` |
| `.ai 忘记 编号` | 删除指定编号的长期记忆；也可以写 `.ai 忘记 全部` 清空。 | `.ai 忘记 1` |

默认内置角色包括 `default`、`assistant`、`creative`、`concise`、`jarvis`；如果管理员配置了自定义角色，以实际列表为准。
回复或引用某条消息再 @ 机器人时，AI 会同时参考被引用消息；如果被引用消息里有图片，也会一并作为图片输入。
开启长期记忆后，机器人会每 3 轮在后台自动总结最近对话，不阻塞当次回复；`.ai 重置` 只清空当前聊天上下文，不删除长期记忆。

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
| 启动成功通知 | OneBot v11 连接成功时 | 私聊通知 `SUPERUSERS`：机器人已启动、QQ 已连接，以及当前后台版本号。 |

## 管理员配置要点

以下配置可写入 `.env`，NoneBot 会按环境变量读取。变量名通常使用大写形式。

### 基础配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `SUPERUSERS` | 空列表 | 管理员 QQ 号列表，例如 `["123456"]`。启动成功通知会发送给这里配置的用户。 |
| `MINGYI_VERSION` | `dev` | 后台版本号。GitHub Actions 构建镜像时会自动写入提交 SHA，通常不需要手动配置。 |

### AI 聊天配置

公共 AI 配置可供未来其他插件复用；`ai_chat` 会优先读取自己的 `AICHAT_*` 配置，未配置时回退到公共 AI 配置。联网工具开关保留在插件维度，不提供全局 `AI_WEB_SEARCH`。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `AI_KEY` | 空 | OpenAI 兼容接口的通用 API Key。 |
| `AI_BASEURL` | 空 | OpenAI 兼容 Responses API 的通用 Base URL，例如 `https://api.gptsapi.net/v1`。不要填到 `/responses`。 |
| `AI_MODEL` | 空 | 通用 AI 模型名。 |

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `AICHAT_KEY` | 空 | AI 聊天专用 API Key；为空时回退到 `AI_KEY`。 |
| `AICHAT_BASEURL` | 空 | AI 聊天专用 Base URL；为空时回退到 `AI_BASEURL`。 |
| `AICHAT_MODEL` | 空 | AI 聊天使用的模型名；为空时回退到 `AI_MODEL`。 |
| `AICHAT_WEB_SEARCH` | `false` | 是否启用 Responses API 的 `web_search` 联网工具。图片解析始终走 Responses API 的 `input_image`。 |
| `AICHAT_DEFAULT_ROLE` | `default` | 默认聊天角色。 |
| `AICHAT_HISTORY_LIMIT` | `12` | 每个会话保留的消息条数，包含 system 消息；裁剪时会保留完整问答轮次。 |
| `AICHAT_ROLES_PATH` | `data/ai_chat_roles.json` | 角色配置文件路径。首次启动会自动生成默认角色文件。 |
| `AICHAT_SESSION_TTL_MINUTES` | `1440` | 会话上下文过期时间，单位分钟。 |
| `AICHAT_MEMORY_ENABLED` | `true` | 是否启用 AI 长期记忆。 |
| `AICHAT_MEMORY_PATH` | `data/ai_chat_memories.json` | 长期记忆持久化文件路径。 |
| `AICHAT_MEMORY_MAX_ITEMS` | `20` | 每个用户最多保留的长期记忆条数。 |
| `AICHAT_MEMORY_SUMMARY_INTERVAL` | `3` | 每个用户每多少轮成功对话触发一次后台自动总结；小于等于 0 时不自动总结。 |

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
└── src
    ├── common
    │   └── ai
    └── plugins
        ├── ai_chat
        ├── coc7
        ├── daily_news
        ├── help
        ├── ping
        ├── repeater
        ├── startup_notify
        └── sunset
```

后续插件建议按功能放到 `src/plugins/<插件名>/__init__.py`。
