from nonebot import get_driver, logger, on_type
from nonebot.adapters.onebot.v11 import Bot
from nonebot.adapters.onebot.v11.event import FriendRequestEvent, GroupRequestEvent
from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="request_handler",
    description="自动通过好友请求和邀请机器人入群请求，并通知 SUPERUSERS。",
    usage="配置 SUPERUSERS 后自动处理 OneBot v11 请求事件。",
)


driver = get_driver()


def _is_group_invite_event(event: GroupRequestEvent) -> bool:
    return event.sub_type == "invite"


friend_request = on_type(FriendRequestEvent, priority=1, block=True)
group_invite = on_type(GroupRequestEvent, _is_group_invite_event, priority=1, block=True)


def get_superuser_ids() -> list[str]:
    return [str(user_id).strip() for user_id in driver.config.superusers if str(user_id).strip()]


def _format_comment(comment: str | None) -> str:
    text = (comment or "").strip()
    return text or "无"


def build_friend_request_notification(event: FriendRequestEvent) -> str:
    return "\n".join(
        [
            "已自动通过好友请求。",
            f"好友 QQ：{event.user_id}",
            f"验证信息：{_format_comment(event.comment)}",
        ]
    )


def build_group_invite_notification(event: GroupRequestEvent, group_name: str | None = None) -> str:
    lines = ["已自动通过群邀请，机器人已加入群聊。"]
    if group_name:
        lines.append(f"群名：{group_name}")
    lines.extend(
        [
            f"群号：{event.group_id}",
            f"邀请人 QQ：{event.user_id}",
            f"验证信息：{_format_comment(event.comment)}",
        ]
    )
    return "\n".join(lines)


async def _fetch_group_name(bot: Bot, group_id: int) -> str | None:
    try:
        info = await bot.get_group_info(group_id=group_id, no_cache=True)
    except Exception as exc:
        logger.warning("Request handler failed to fetch group info for {}: {}", group_id, exc)
        return None

    name = str(info.get("group_name") or "").strip()
    return name or None


async def _notify_superusers(bot: Bot, message: str) -> None:
    owner_ids = get_superuser_ids()
    if not owner_ids:
        logger.warning("Request handler notification skipped: SUPERUSERS is empty.")
        return

    for owner_id in owner_ids:
        if not owner_id.isdigit():
            logger.warning("Request handler skipped invalid SUPERUSERS id: {}", owner_id)
            continue

        try:
            await bot.send_private_msg(user_id=int(owner_id), message=message)
        except Exception as exc:
            logger.warning("Request handler failed to notify superuser {}: {}", owner_id, exc)


@friend_request.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent) -> None:
    try:
        await event.approve(bot)
    except Exception:
        logger.exception("Auto approving friend request from {} failed.", event.user_id)
        return

    await _notify_superusers(bot, build_friend_request_notification(event))


@group_invite.handle()
async def handle_group_invite(bot: Bot, event: GroupRequestEvent) -> None:
    try:
        await event.approve(bot)
    except Exception:
        logger.exception("Auto approving group invite for group {} failed.", event.group_id)
        return

    group_name = await _fetch_group_name(bot, event.group_id)
    await _notify_superusers(bot, build_group_invite_notification(event, group_name=group_name))
