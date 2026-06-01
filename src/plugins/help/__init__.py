from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata


HELP_TEXT = """可用指令：
.help、.帮助、。菜单 - 查看这份指令说明
.ping、.状态 - 检查机器人是否在线
.数据库测试、.mysql测试、.db测试 - 管理员测试 MySQL 连接
.配置 查看 - 管理员查看当前群运行时配置
.配置 每日新闻 开/关、.配置 火烧云城市 上海 - 管理员热修改当前群配置
.更新、.部署更新 - 管理员触发镜像更新
.重启 - 管理员重启机器人并重新读取 .env
今日新闻、.今日新闻、。今日新闻 - 获取今日 60s 新闻
sun 上海、.sun 上海、。火烧云 广州 - 查询火烧云
.r 2d6+3、.r1d100、。rd50 - 投骰
。r尝试驾驶汽车、.r 1d20 撬锁 - 投骰并让 AI 短评
.ra 侦查 60 - COC7 普通检定
.coc、.coc3、。coc 10 - 快速生成 COC7 调查员
.ai - 查看 AI 角色
.ai 角色名 - 切换 AI 角色
.ai 重置 - 清空当前 AI 上下文
.ai 记忆 - 查看长期记忆
.ai 记住 内容 - 手动保存长期记忆
.ai 忘记 编号 - 删除长期记忆
.ai 整理记忆 - 管理员整理长期记忆

群聊中 @我 加内容，或私聊我，可以直接聊天。"""


__plugin_meta__ = PluginMetadata(
    name="help",
    description="展示用户可用指令。",
    usage=".help\n.帮助\n.菜单",
)


help_command = on_regex(r"^[.。](?:help|帮助|菜单)$", priority=5, block=True)


@help_command.handle()
async def handle_help_command(event: MessageEvent) -> None:
    await help_command.finish(MessageSegment.text(HELP_TEXT))
