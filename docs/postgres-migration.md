# MySQL → PostgreSQL 全量迁移

> 历史迁移记录。Watchtower 已退役，文内相关启停步骤仅保留历史背景；当前部署以 README 的 Mac 本地流程为准。

## 发布与配置

`DB_BACKEND` 可选 `mysql` / `postgres`，默认 `mysql`。现有 `MYSQL_*` 配置继续有效。
PG 使用 `POSTGRES_HOST`、`POSTGRES_PORT`（默认 5432）、`POSTGRES_DATABASE`、
`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_CONNECT_TIMEOUT_SECONDS`。
`AICHAT_MEMORY_BACKEND=auto` 默认跟随 `DB_BACKEND`；显式 `mysql`、`postgres`、`json` 仍有效。
切换时必须确认 AI 记忆没有被显式锁定到旧后端。

选定 PG 后不会自动回退 MySQL。PG 不自动导入旧 JSON 记忆文件；历史 SQL 数据由迁移工具导入。
`.数据库测试` / `.db测试` / `.mysql测试` / `.pg测试` 显示当前公共数据库连接。
如果显式指定了独立的 AI 记忆后端，还需要单独验证记忆读写。

三个业务表的 ID、时间、空值、JSON 文本和归档记录均保留；时间使用无时区 timestamp，
保持现有应用的 UTC 转换逻辑。PG 默认字符串比较区分大小写，与 MySQL 的
`utf8mb4_unicode_ci` 不完全相同：机器人生成的 scope、数字 ID、配置键及 SHA-256
键采用固定格式；外部手工写入时不要依赖大小写或重音折叠。迁移逐值验证，不规范化数据。

实际历史群名片含 NUL 字符，因此 `group_message_records.sender_card` 在 PG 中使用
`bytea` 保存完整 UTF-8 字节。应用写入时编码，迁移比较时严格解码还原，包含 NUL 的值
也逐字符校验。SQL 客户端显示该列时可能显示十六进制；不能对含 NUL 的值直接调用
`convert_from` 转成 PG text。其他字段若出现 NUL，预检查仍会停止并报告。
这一限制见 [PG 字符类型](https://www.postgresql.org/docs/17/datatype-character.html)
和 [二进制类型](https://www.postgresql.org/docs/17/datatype-binary.html)。

## 操作工具

先在 PG 创建独立库和专用账号。迁移配置文件同时包含源 `MYSQL_*` 与目标 `POSTGRES_*`，
使用受限权限，不提交 Git。不把密码放在命令行、日志或报告中。

```sh
python -m src.common.db.migrate precheck --config /secure/migration.env --report /secure/precheck.json
python -m src.common.db.migrate import --config /secure/migration.env --source-stopped \
  --backup /secure/source-snapshot.jsonl.gz --report /secure/import.json
python -m src.common.db.migrate verify --config /secure/migration.env --report /secure/verify.json
```

先对独立试迁移库执行以上流程。试迁移期间源仍在线时，导入内部的快照校验是有效的；
随后独立执行 verify 若源已有新增或修改可能失败，不能视为正式停机验收。
正式导入必须停止所有机器人写入实例，`--source-stopped` 是操作员的确认，不会自动停止机器人。

工具只读源端，检查预期表、InnoDB 引擎、字符和整数范围；拒绝未知业务表或非空目标表。
目标建表使用自己的版本记录。三张表在一个事务中导入并逐字段计算规范化 SHA-256，
随后事务性重置自增序列。失败回滚业务数据，不清空已有数据。SQL 结构初始化是独立事务。
不复制 MySQL 的建表版本记录，不执行业务裁剪。备份和报告不覆盖已有文件。

gzip JSONL 是同一源快照的逻辑副本，包含表名、列名及带类型的值。
正式切换另外保留原生 `mysqldump --single-transaction --hex-blob --no-tablespaces`
备份（在 NAS 的 MySQL 容器中执行、密码通过容器环境提供），并备份原 `.env`。
使用迁移账号执行 dump 前确认读取权限；不要为了 dump 放宽业务账号全局权限。
失败报告仅记录异常类型，防止驱动异常泄露消息内容。失败后保持原配置并诊断，不启动 PG 写入。

## Mac Docker / NAS 共享目录切换

本部署的共享配置位于 NAS `/volume1/docker/MingYiBot/.env`，挂载到 `/app/.env`。
PG 位于 `192.168.100.150:55432`。先发布兼容镜像并确认 Mac 已加载对应提交：

```sh
docker exec mingyi-bot printenv MINGYI_VERSION
```

代码在启动时重新读取 `/app/.env` 并覆盖旧容器环境，因此改共享文件后必须重启应用。
如共享挂载未反映文件更新，应重建容器，不能仅依据宿主文件内容认定切换成功。

1. 在 Mac 执行 `docker stop mingyi-watchtower`，再执行 `docker stop -t 120 mingyi-bot`。
   用 `docker inspect --format '{{.Name}} {{.State.Running}} {{.State.ExitCode}}' mingyi-watchtower mingyi-bot`
   确认停止；若机器人被强制终止，检查归档队列是否排空后再继续。
2. 在 NAS 备份源库和原配置，执行最终导入及独立校验。停机期间没有自动补录消息的保证。
3. 校验成功后更新共享 `.env`：`DB_BACKEND=postgres`、`AICHAT_MEMORY_BACKEND=auto` 及 PG 凭据；保留原 MySQL 配置。
4. Mac 执行 `docker start mingyi-bot`，检查版本、启动日志、`.数据库测试`、旧记忆读取、
   新消息归档和设置读写。通过后执行 `docker start mingyi-watchtower`。

PG 首次业务写入前可恢复 `.env` 并重启回退；已经有 PG 写入时，必须先停机并备份两端，
核对并反向同步新增、修改和删除后才能回退，不能直接切回旧 MySQL。
旧库和备份至少保留 30 天；本迁移工具不删除它们。

## 测试

普通测试：`python -m unittest discover -s tests`。
数据库改动需要回归时，在本地使用独立 MySQL 8.4 / PostgreSQL 17 测试服务运行相关测试。GitHub Actions 已撤下，不连接生产库运行测试。
本地真实集成测试设置 `INTEGRATION_DB=1` 与 `INTEGRATION_ENV=/secure/test.env`；
两个库名必须以 `mingyibot_test` 开头，测试会清理这两个测试库的业务表。
测试覆盖两个后端的写入去重、记忆裁剪/归档、配置更新、重复建表、完整迁移校验、
重复导入拒绝、自增 ID 校准和跨表失败回滚。
