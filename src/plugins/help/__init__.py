from nonebot import on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata


HELP_TEXT = """可用指令：
.help - 查看这份指令说明
.ping - 检查机器人是否在线
.今日新闻 - 获取今日 60s 新闻
.sun 上海 - 查询火烧云
.r 2d6+3 - 投骰
.ra 侦查 60 - COC7 普通检定
.coc - 快速生成 COC7 调查员
.ai - 查看 AI 角色
.ai 角色名 - 切换 AI 角色
.ai 重置 - 清空当前 AI 上下文"""


__plugin_meta__ = PluginMetadata(
    name="help",
    description="展示用户可用指令。",
    usage=".help\n.帮助\n.菜单",
)


help_command = on_regex(r"^[.。](?:help|帮助|菜单)$", priority=5, block=True)


@help_command.handle()
async def handle_help_command(event: MessageEvent) -> None:
    await help_command.finish(MessageSegment.text(HELP_TEXT))
