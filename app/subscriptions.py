from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app import db

ACTIVE_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


async def missing_channels(bot: Bot, user_id: int) -> list[dict]:
    missing: list[dict] = []
    for channel in await db.get_channels():
        try:
            member = await bot.get_chat_member(channel["chat_id"], user_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            missing.append(channel)
            continue
        if member.status not in ACTIVE_STATUSES:
            missing.append(channel)
    return missing


def channel_url(channel: dict) -> str | None:
    if channel.get("invite_link"):
        return channel["invite_link"]
    username = channel.get("username")
    if username:
        return f"https://t.me/{username.lstrip('@')}"
    return None
