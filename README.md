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

## 内置指令

- `/ping`：回复 `pong`
- `/状态`：回复 `pong`

## 目录结构

```text
.
├── bot.py
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── src/plugins
    └── ping
        └── __init__.py
```

后续插件建议按功能放到 `src/plugins/<插件名>/__init__.py`。
