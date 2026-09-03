from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.config import is_admin


def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="❓ Помощь")]]
    if is_admin(user_id):
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def subscribe_keyboard(channels: list[dict], check: bool = True) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for channel in channels:
        url = channel.get("invite_link")
        username = channel.get("username")
        if not url and username:
            url = f"https://t.me/{username.lstrip('@')}"
        if not url:
            continue
        buttons.append(
            [InlineKeyboardButton(text=f"📢 {channel['title']}", url=url)]
        )
    if check:
        buttons.append(
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subs")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить подписку", callback_data="admin:add_sub")],
            [InlineKeyboardButton(text="➖ Удалить подписку", callback_data="admin:del_sub")],
            [InlineKeyboardButton(text="📋 Список подписок", callback_data="admin:list_sub")],
            [InlineKeyboardButton(text="📣 Рассылка", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        ]
    )


def delete_channels_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"❌ {channel['title']}",
                callback_data=f"admin:rm:{channel['id']}",
            )
        ]
        for channel in channels
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")]
        ]
    )


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="admin:bc_yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel"),
            ]
        ]
    )


def add_to_group_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить бота в группу",
                    url=f"https://t.me/{bot_username}?startgroup=true",
                )
            ]
        ]
    )
