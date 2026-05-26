from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata


HELP_TEXT = """可用指令：
/help、help、帮助、菜单 - 查看这份指令说明
/ping、状态 - 检查机器人是否在线
/今日新闻、今日新闻 - 获取今日 60s 新闻
/sun 上海、sun 北京、火烧云 广州 - 查询火烧云
.r 2d6+3、.r1d100、。rd50 - 投骰
.ra 侦查 60 - COC7 普通检定
.coc、.coc3、。coc 10 - 快速生成 COC7 调查员
/ai - 查看 AI 角色
/ai 角色名 - 切换 AI 角色
/ai 重置 - 清空当前 AI 上下文

群聊中 @我 加内容，或私聊我，可以直接聊天。"""


__plugin_meta__ = PluginMetadata(
    name="help",
    description="展示用户可用指令。",
    usage="/help\nhelp\n帮助\n菜单",
)


help_command = on_command("help", aliases={"帮助", "菜单"}, priority=5, block=True)
help_alias = on_regex(r"^(?:help|帮助|菜单)$", priority=5, block=True)


@help_command.handle()
async def handle_help_command(event: MessageEvent) -> None:
    await help_command.finish(MessageSegment.text(HELP_TEXT))


@help_alias.handle()
async def handle_help_alias(event: MessageEvent) -> None:
    await help_alias.finish(MessageSegment.text(HELP_TEXT))
