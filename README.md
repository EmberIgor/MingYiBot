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

## Docker Compose 部署

```bash
cp .env.example .env
docker compose up -d
```

根目录的 `docker-compose.yml` 会同时启动 `mingyi-bot` 和 `mingyi-watchtower`，适合在 Mac、NAS 或群晖 Container Manager 中使用同一份配置。默认会把容器内的 `8080` 端口映射到宿主机 `8080`。如果端口被占用，可以在 `.env` 中修改：

```dotenv
BOT_PORT=18080
```

随后把 NapCat/Lagrange 的反向 WebSocket 地址改为：

```text
ws://宿主机IP:18080/onebot/v11/ws
```

## 群晖自动部署

生产环境推荐使用 GitHub Actions 构建镜像并推送到 GHCR，群晖只负责拉取新镜像和重启容器。这样每次 `git push` 到 `main` 后，不需要在 Container Manager 里删除项目再重建。

如果只使用群晖 Container Manager 图形界面，项目路径直接选择本仓库根目录即可。根目录的 `docker-compose.yml` 已经把机器人和 Watchtower 放在同一个项目里。

### 1. GitHub Actions

仓库内的 `.github/workflows/docker-image.yml` 会在 `main` 分支 push 或手动触发时构建镜像，并推送：

```text
ghcr.io/emberigor/mingyibot:latest
ghcr.io/emberigor/mingyibot:<commit-sha>
```

如果在 GitHub 仓库 Secrets 中配置了 `DOCKERHUB_TOKEN`，同一次构建也会推送到 Docker Hub：

```text
emberigor/mingyibot:latest
emberigor/mingyibot:<commit-sha>
```

`latest` 用于日常自动更新，提交 SHA tag 用于回滚。

### 2. 群晖首次部署

在群晖项目根目录准备 `.env`，也就是 `.env.example` 所在目录：

```bash
cp .env.example .env
```

`docker-compose.yml` 会通过 `env_file: .env` 把配置注入容器，并把同一份文件只读挂载到容器内的 `/app/.env`。这样即使群晖 Container Manager 没有正确处理 `env_file`，NoneBot 启动时也能直接读取 `/app/.env`。不要只依赖 `environment` 里的 `${变量:-}` 插值；在部分群晖 Container Manager 场景下，插值阶段读不到 `.env` 时会把这些值展开成空字符串。

如果 GHCR 镜像是私有的，先在群晖 SSH 中登录 GHCR。这个 token 只需要 GitHub `read:packages` 权限，用于首次手动 `pull`：

```bash
docker login ghcr.io
```

然后启动完整项目：

```bash
docker compose pull
docker compose up -d
```

如果使用 Container Manager：

1. 打开 Container Manager。
2. 进入“项目”。
3. 选择“新增”。
4. 项目名称填写 `mingyibot`。
5. 路径选择本仓库根目录，例如 `/volume1/docker/MingYiBot`。
6. 使用该目录现有的 `docker-compose.yml` 创建项目。
7. 在项目根目录准备 `.env`，内容按 `.env.example` 填写；如果镜像是私有的，额外填写 `REPO_USER` 和 `REPO_PASS`。
8. 创建并启动项目。

### 3. 自动拉取新镜像

根目录 compose 已经内置 Watchtower。它会只更新带有 Watchtower 标签的 `mingyi-bot` 容器，默认每 60 秒检查一次。

如果 GHCR 镜像是私有的，还需要让 Watchtower 自己带上拉取凭据。在 `.env` 中填写：

```dotenv
REPO_USER=你的GitHub用户名
REPO_PASS=只包含read:packages权限的GitHub PAT
```

如需调整检查间隔，可以在 `.env` 中设置：

```dotenv
WATCHTOWER_POLL_INTERVAL=600
```

可以额外配置 HTTP API token，让管理员在 QQ 中发送 `.更新` 或 `.部署更新` 立即触发一次镜像检查：

```dotenv
WATCHTOWER_HTTP_API_TOKEN=一串随机长字符串
```

这个接口只在 Compose 内部网络给机器人调用，不需要暴露到群晖宿主机端口。不要使用 `.env.example` 里的占位 token，部署时请换成自己的随机长字符串。

### 4. 日常更新和配置变更

只改机器人代码时，把代码推送到 `main`，等待 GitHub Actions 构建成功和 Watchtower 自动拉取即可。

如果本次更新只修改了机器人运行时读取的 `.env` 配置，例如 `HERMES_*`、`AICHAT_*`、`AI_*`、`DAILYNEWS_*`、`SUNSET_*`、`WATCHTOWER_HTTP_API_*`，更新 `.env` 后发送 `.重启`，或重启 `mingyi-bot` 容器即可。项目启动时会主动读取挂载到容器内的 `/app/.env`，并覆盖 Docker 创建容器时注入的旧环境变量。

如果本次更新涉及以下内容，Watchtower 不会自动应用，普通容器重启也不一定生效，需要在群晖 Container Manager 中重建项目，或用 SSH 执行 `docker compose up -d --force-recreate`：

- `docker-compose.yml` 等 Compose 文件。
- `.env` 中会影响 Docker/Compose 本身的配置项，例如 `BOT_PORT`、`WATCHTOWER_POLL_INTERVAL`、`WATCHTOWER_CLEANUP`。
- 端口、挂载目录、`env_file`、`volumes`、`environment`、网络等容器配置。
- `data/` 下已经持久化的运行时配置和旧 AI 记忆备份。

如果使用 SSH，也可以在项目根目录执行：

```bash
docker compose pull
docker compose up -d --force-recreate
```

### 5. 回滚

如果要回滚，把 `.env` 里的 `MINGYI_IMAGE` 从 `latest` 临时改成某个历史提交 SHA tag，然后执行：

```bash
docker compose pull
docker compose up -d
```

## 当前功能

- 基础状态检查：确认机器人在线状态。
- 性能测试：管理员可查看当前机器人实例的事件延迟和本地处理耗时。
- 帮助菜单：快速查看用户可用指令。
- 群聊复读：群内连续出现相同消息达到 2 条时，机器人自动复读一次。
- AI 聊天：在群里 @ 机器人，或私聊机器人时进行 AI 对话；Hermes 负责正式人格、会话和长期记忆，现有模型接口提供断线保底。
- COC7 工具：支持基础骰子、暗骰、技能检定和快速调查员生成。
- 火烧云查询：查询指定城市今日、明日的日出/日落火烧云分析；支持定时私聊提醒。
- 每日新闻：手动获取 60s 每日新闻图片；支持每天定时向群推送。
- VV 表情包：按台词关键词搜索并发送匹配度最高的 VV 视频帧。
- MySQL 自检：管理员可以测试 MySQL 连接，方便后续接入数据库功能前先验证群晖配置。
- 运行时配置：管理员可以热修改每日新闻、火烧云默认城市、备用 AI 联网、复读阈值和群消息记录。
- 群消息记录：管理员可按群开启消息归档，为后续群画像等能力保留数据基础。
- 部署更新：管理员可以在 QQ 中触发 Watchtower 立即检查新镜像，也可以重启机器人重新读取 `.env`。

## 用户可用命令

命令通常可以在群聊或私聊中使用；其中 AI 聊天在群聊里需要 @ 机器人触发。以下示例里的空格建议保留。

### 基础命令

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.help` | 查看用户可用指令摘要。也可以写作 `.帮助`、`.菜单`，并支持中文句号。 | `.help` |
| `.ping` | 检查机器人是否在线，回复 `pong`。也可以写作 `.状态`。 | `.ping` |
| `.数据库测试` | 管理员测试 MySQL 是否可连接。也可以写作 `.mysql测试`、`.db测试`，并支持中文句号。 | `.数据库测试` |
| `.性能测试` | 管理员查看机器人事件延迟和本地处理耗时。也可以写作 `.延迟测试`、`.perf`，并支持中文句号。 | `.性能测试` |
| `.配置 查看` | 管理员查看当前群的运行时配置。 | `.配置 查看` |
| `.配置 配置项 值` | 管理员热修改当前群配置；支持每日新闻定时推送、火烧云城市、备用 AI 联网、复读阈值和群消息记录。 | `.配置 火烧云城市 上海` |
| `.配置 重置 配置项` | 删除当前群的运行时覆盖配置，恢复 `.env` 默认值。 | `.配置 重置 火烧云城市` |
| `.群记录 状态` | 查看当前群消息记录是否开启，以及保留天数。 | `.群记录 状态` |
| `.群记录 开启` | 管理员开启当前群消息记录。默认不记录，需要显式开启或私聊设置全局默认。 | `.群记录 开启` |
| `.群记录 关闭` | 管理员关闭当前群消息记录。 | `.群记录 关闭` |
| `.群记录 保留 天数` | 管理员设置当前群消息记录保留天数。 | `.群记录 保留 90` |
| `.更新` | 管理员触发 Watchtower 立即检查并更新镜像。也可以写作 `.部署更新`。 | `.更新` |
| `.重启` | 管理员重启机器人进程并重新读取 `.env`。 | `.重启` |

### AI 聊天

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `@机器人 内容` | 与 AI 对话，`@机器人` 可以放在消息任意位置。Hermes 会话按“群/用户”或私聊用户区分。 | `@茗懿 帮我想一个跑团导入` |

回复或引用某条消息再 @ 机器人时，AI 会同时参考被引用消息；如果被引用消息里有图片，也会一并作为图片输入。
旧 `.ai` 命令已移除。旧角色文件和记忆数据保留作备份，机器人不再读取或写入；Hermes 的设置请参阅 [交接文件](docs/hermes-public-profile-handoff.md)。

### COC7 骰子与规则

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.r 表达式/理由` | 投掷骰子表达式；不填表达式时默认 `1d100`。也可以直接写投掷理由，AI 可用时会追加短评。 | `.r 2d6+3`、`。r尝试驾驶汽车`、`.r 1d20 撬锁` |
| `.rh 表达式/理由` | 暗骰；解析规则同 `.r`，群聊中需要先添加机器人好友，结果通过普通私聊发送。 | `.rh 1d100`、`。rh侦查` |
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
如果开启“必须是当天新闻”的检查，而新闻源还没更新，机器人会提示“今日新闻还没有更新，请稍后再试”。群聊每日新闻定时推送开关不会影响手动 `.今日新闻` 命令。

### VV 表情包

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.vv 关键词` | 搜索并发送匹配度最高的一张 VV 表情包，也支持中文句号。 | `.vv 遥遥领先` |

VV 查询可在群聊和私聊中使用，无需 @ 机器人。默认每个群独立冷却 10 秒，私聊按用户独立冷却；上游服务不可用时不会影响机器人其他功能。

### 自动触发功能

| 功能 | 触发方式 | 说明 |
| --- | --- | --- |
| 群聊复读 | 同一群内连续 2 条相同消息 | 机器人只会在第二条相同消息出现时复读一次，之后同一轮不会反复刷屏。 |
| 每日新闻定时推送 | 默认每天 `08:30` | 推送到允许范围内的群；如果新闻尚未更新，会按配置重试，默认最晚等到 `10:10`。 |
| 火烧云私聊提醒 | 默认每天 `09:00`、`21:00` | 当默认城市的火烧云等级达到阈值时，私聊提醒管理员或配置的接收人。 |
| 启动成功通知 | OneBot v11 连接成功时 | 私聊通知 `SUPERUSERS`：机器人已启动、QQ 已连接，以及当前后台版本号。 |
| 请求自动处理 | 收到好友请求或邀请机器人入群时 | 自动通过请求，并私聊通知 `SUPERUSERS` 添加的好友 QQ 或加入的群号。 |

## 管理员配置要点

以下配置可写入 `.env`，NoneBot 会按环境变量读取。变量名通常使用大写形式。

### 基础配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `SUPERUSERS` | 空列表 | 管理员 QQ 号列表，例如 `["123456"]`。启动成功通知和请求自动处理通知会发送给这里配置的用户。 |
| `MINGYI_VERSION` | `dev` | 后台版本号。GitHub Actions 构建镜像时会自动写入提交 SHA，通常不需要手动配置。 |

### 部署更新配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `WATCHTOWER_POLL_INTERVAL` | `60` | Watchtower 自动检查镜像更新的间隔，单位秒。 |
| `WATCHTOWER_HTTP_API_TOKEN` | `change-me-random-token` | Watchtower HTTP API 鉴权 token；部署时请改成随机长字符串。 |
| `WATCHTOWER_HTTP_API_URL` | `http://watchtower:8080/v1/update` | 机器人触发 Watchtower 更新的内部地址。 |
| `WATCHTOWER_UPDATE_IMAGE` | `ghcr.io/emberigor/mingyibot:latest` | 手动触发更新时检查的镜像。 |
| `WATCHTOWER_HTTP_TIMEOUT_SECONDS` | `10` | 机器人请求 Watchtower HTTP API 的超时时间，单位秒。 |

### MySQL 测试配置

这些配置用于管理员命令 `.数据库测试`、AI 长期记忆、运行时配置中心和群消息记录，用于验证并连接机器人使用的 MySQL 数据库。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `MYSQL_HOST` | 空 | MySQL 地址。如果 MySQL 和机器人在同一个 Compose 项目网络里，可以填 `mysql`；如果 MySQL 是群晖界面单独创建的容器，可以填群晖局域网 IP。 |
| `MYSQL_PORT` | `3306` | MySQL 端口。同 Compose 网络里通常填容器端口 `3306`；通过群晖局域网 IP 访问时，填 DSM 端口映射里的本地端口，例如 `13306`。 |
| `MYSQL_DATABASE` | `mingyibot` | 测试连接时使用的数据库名。 |
| `MYSQL_USER` | `mingyi` | 测试连接时使用的数据库用户名。 |
| `MYSQL_PASSWORD` | 空 | `MYSQL_USER` 对应的密码。 |
| `MYSQL_CONNECT_TIMEOUT_SECONDS` | `5` | 连接超时时间，单位秒。 |

群晖上如果是单独创建的 MySQL 容器，机器人 `.env` 可以先这样填：

```dotenv
MYSQL_HOST=群晖局域网IP
MYSQL_PORT=13306
MYSQL_DATABASE=mingyibot
MYSQL_USER=mingyi
MYSQL_PASSWORD=你的MySQL应用密码
```

### 群消息记录配置

群消息记录默认关闭，建议由管理员在需要的群里发送 `.群记录 开启` 后再开始入库。记录内容用于后续词云、群画像等能力的数据基础；插件会保存消息文本、消息段类型、发送者 QQ、群号、时间和有限的消息段 JSON。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `MESSAGE_ARCHIVE_ENABLED` | `false` | 群消息记录的默认开关。为保护隐私，建议保持关闭并按群开启。 |
| `MESSAGE_ARCHIVE_RETENTION_DAYS` | `90` | 默认保留天数；也可在群里用 `.群记录 保留 90` 覆盖。 |
| `MESSAGE_ARCHIVE_QUEUE_SIZE` | `1000` | 消息归档后台队列容量；队列满时丢弃新记录，避免影响机器人响应。 |
| `MESSAGE_ARCHIVE_WORKERS` | `2` | 归档队列消费者数量。 |
| `MESSAGE_ARCHIVE_BATCH_SIZE` | `50` | 每次数据库批量写入的最大消息数。 |
| `MESSAGE_ARCHIVE_FLUSH_INTERVAL_SECONDS` | `0.5` | 未达到批量上限时的最长等待秒数。 |

开启后会通过 migration 创建 `group_message_records` 表。消息通过有界队列批量写入，超过保留期的数据由每日后台任务清理；如果数据库不可用或队列已满，消息记录会跳过并限频写日志，不影响其他群聊功能。

### AI 聊天配置

Hermes 是聊天主后端。填写 `HERMES_BASEURL` 和 `HERMES_KEY` 后，机器人向该 profile 的 Responses API 发送当前消息，由 Hermes 管理正式会话和记忆。未配置或无法连接 Hermes 时，使用 `AICHAT_*`（为空则使用 `AI_*`）作为基础人格保底。保底联网由 MingYiBot 的 Exa 工具负责，Hermes 联网能力在 Hermes profile 中配置。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `AI_KEY` | 空 | OpenAI 兼容接口的通用 API Key。 |
| `AI_BASEURL` | 空 | OpenAI 兼容 Responses API 的通用 Base URL，例如 `https://api.gptsapi.net/v1`。不要填到 `/responses`。 |
| `AI_MODEL` | 空 | 通用 AI 模型名。 |

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `HERMES_BASEURL` | 空 | Hermes 专用 profile 的 API Base URL，以 `/v1` 结尾；机器人会追加 `/responses`。容器内必须可访问。 |
| `HERMES_KEY` | 空 | 该 profile 的 API Server Key。 |
| `HERMES_MODEL` | `mingyi-public` | Hermes 对外公布的模型别名。 |
| `HERMES_REQUEST_TIMEOUT_SECONDS` | `120` | Hermes 单次请求超时秒数。已发出请求后的超时不自动切换备用模型。 |
| `AICHAT_KEY` | 空 | 保底模型 API Key；为空时回退到 `AI_KEY`。 |
| `AICHAT_BASEURL` | 空 | 保底模型 Base URL；为空时回退到 `AI_BASEURL`。 |
| `AICHAT_MODEL` | 空 | 保底模型名；为空时回退到 `AI_MODEL`。 |
| `AICHAT_WEB_SEARCH` | `false` | 保底模式是否允许调用 Exa 联网搜索。 |
| `EXA_API_KEY` | 空 | 保底模式启用 Exa 联网时必填。 |
| `EXA_TIMEOUT_SECONDS` | `15` | 单次 Exa 搜索超时秒数，必须大于 0。 |
| `EXA_NUM_RESULTS` | `5` | 单次搜索结果数，范围 1–10。 |
| `EXA_HIGHLIGHT_MAX_CHARACTERS` | `1200` | 每个结果返回给模型的相关片段字符上限，范围 100–10000。 |
| `AICHAT_HISTORY_LIMIT` | `12` | 保底模式每个会话保留的消息条数。 |
| `AICHAT_SESSION_TTL_MINUTES` | `1440` | 保底模式上下文闲置过期时间，单位分钟；不影响 Hermes 中的历史。 |
| `AICHAT_MAX_CONCURRENCY` | `5` | 所有会话同时请求 AI 模型的最大数量。 |
| `AICHAT_REQUEST_TIMEOUT_SECONDS` | `60` | 保底模型请求超时秒数。 |

保底模式下启用 AI 联网后，模型可按需调用 Exa，成功搜索的回答末尾会追加来源。保底对话仅在机器人内存中短暂保存，不进入旧记忆库，也不会在 Hermes 恢复后自动补写。

### 运行时配置中心

`.env` 仍然负责数据库连接、API Key、token、容器端口等敏感或部署级配置。运行时配置只保存可热修改的非敏感群配置，并写入 MySQL 的 `runtime_settings` 表；数据库不可用时，各插件会回退到 `.env` 默认值，只有 `.配置` 命令会提示不可用。

读取优先级为：

```text
代码默认值 < .env < 数据库 global 覆盖 < 数据库 group/user 覆盖
```

群聊中默认修改当前群配置：

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.配置 查看` | 查看当前群运行时配置。 | `.配置 查看` |
| `.配置 每日新闻 开/关` | 覆盖当前群每日新闻定时推送开关，不影响手动 `.今日新闻`。 | `.配置 每日新闻 关` |
| `.配置 火烧云城市 城市` | 覆盖当前群火烧云默认城市；只影响不填地点的手动查询。 | `.配置 火烧云城市 上海` |
| `.配置 AI联网 开/关` | 覆盖当前群保底模型是否允许调用 Exa 联网工具；不影响 Hermes。 | `.配置 AI联网 开` |
| `.配置 复读阈值 数字` | 覆盖当前群复读阈值；小于 2 表示关闭复读。 | `.配置 复读阈值 3` |
| `.配置 群记录 开/关` | 覆盖当前群消息记录开关。也可以用 `.群记录 开启/关闭`。 | `.配置 群记录 开` |
| `.配置 群记录保留 天数` | 覆盖当前群消息记录保留天数。也可以用 `.群记录 保留 90`。 | `.配置 群记录保留 90` |
| `.配置 重置 配置项` | 删除当前群某项覆盖配置，恢复 `.env` 默认。 | `.配置 重置 AI联网` |

私聊中默认修改全局配置，用于批量调整所有未设置群覆盖的默认值：

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `.配置 查看` | 查看全局运行时配置。 | `.配置 查看` |
| `.配置 每日新闻 开/关` | 覆盖全局每日新闻定时推送默认开关，不影响手动 `.今日新闻`。 | `.配置 每日新闻 关` |
| `.配置 火烧云城市 城市` | 覆盖全局火烧云默认城市。 | `.配置 火烧云城市 上海` |
| `.配置 AI联网 开/关` | 覆盖全局保底模型是否允许调用 Exa 联网工具；不影响 Hermes。 | `.配置 AI联网 开` |
| `.配置 复读阈值 数字` | 覆盖全局复读阈值；小于 2 表示关闭复读。 | `.配置 复读阈值 3` |
| `.配置 群记录 开/关` | 覆盖全局群消息记录默认开关，影响所有未设置群覆盖的群。 | `.配置 群记录 开` |
| `.配置 群记录保留 天数` | 覆盖全局群消息记录默认保留天数，影响所有未设置群覆盖的群。 | `.配置 群记录保留 90` |
| `.配置 重置 配置项` | 删除全局覆盖配置，恢复 `.env` 默认。 | `.配置 重置 每日新闻` |

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `RUNTIME_SETTINGS_CACHE_SECONDS` | `30` | 运行时配置读取缓存时间，减少高频消息触发数据库查询。 |

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

每日新闻的群聊运行时开关只控制定时推送，会覆盖 `DAILYNEWS_GROUP_MODE`/`DAILYNEWS_GROUP_IDS` 的默认结果；`DAILYNEWS_ENABLED=false` 仍会关闭定时推送调度。手动 `.今日新闻` 命令不受这些推送范围开关影响。

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

### 复读配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `REPEATER_THRESHOLD` | `2` | 群聊连续出现同一消息达到该次数时复读；小于 2 表示默认关闭复读。 |

### VV 表情包配置

以下配置全部是可选项，代码内置了默认值。旧部署升级镜像后不需要先修改 `.env` 或重建 Compose，即可直接使用 `.vv`；只有需要覆盖默认行为时才添加对应变量。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `VV_API_URL` | `https://vvapi.cicada000.work` | VV 台词搜索服务地址。 |
| `VV_IMAGE_BASE_URL` | `https://vv.noxylva.org` | VV 图片索引和 WebP 数据地址。 |
| `VV_TIMEOUT_SECONDS` | `10` | 搜索、索引和图片请求的超时时间，单位秒。 |
| `VV_COOLDOWN_SECONDS` | `10` | 每群或每位私聊用户的查询冷却时间，单位秒。 |
| `VV_INDEX_CACHE_SECONDS` | `3600` | 图片二进制索引的内存缓存时间，单位秒。 |

数据与检索能力来自 [Cicada000/VV](https://github.com/Cicada000/VV)（GPL-3.0）。该项目提示公开 API 地址可能调整；如上游迁移，可通过上述环境变量覆盖地址。插件只按 Range 下载命中的单帧，不会下载完整的大型 WebP 文件。

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
    │   ├── ai
    │   ├── db
    │   └── settings
    └── plugins
        ├── ai_chat
        ├── coc7
        ├── daily_news
        ├── deploy
        ├── help
        ├── mysql_test
        ├── message_archive
        ├── ping
        ├── repeater
        ├── request_handler
        ├── runtime_config
        ├── startup_notify
        └── sunset
```

后续插件建议按功能放到 `src/plugins/<插件名>/__init__.py`。

## PostgreSQL 支持与迁移

`DB_BACKEND=mysql` 保持原有行为，`DB_BACKEND=postgres` 使用 Psycopg 3 连接 PostgreSQL。
PG 使用 `POSTGRES_*` 配置；切换前必须完成历史数据导入及校验。
详细配置、全量迁移工具、Mac/NAS 切换与回退步骤见 [PostgreSQL 迁移说明](docs/postgres-migration.md)。
