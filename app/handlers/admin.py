from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import db, keyboards
from app.config import is_admin

router = Router()
log = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    add_channel = State()
    wait_broadcast = State()
    confirm_broadcast = State()


def admin_only(user_id: int | None) -> bool:
    return bool(user_id and is_admin(user_id))


async def show_panel(target: Message) -> None:
    count = await db.count_users()
    groups = await db.count_groups()
    channels = await db.get_channels()
    await target.answer(
        "⚙️ <b>Админ-панель</b>\n\n"
        f"Пользователей: <b>{count}</b>\n"
        f"Групп: <b>{groups}</b>\n"
        f"Обязательных подписок: <b>{len(channels)}</b>",
        reply_markup=keyboards.admin_panel_keyboard(),
    )


@router.message(Command("admin"))
@router.message(F.text == "⚙️ Админ-панель")
async def open_admin(message: Message, state: FSMContext) -> None:
    if not admin_only(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await show_panel(message)


@router.callback_query(F.data == "admin:back")
@router.callback_query(F.data == "admin:cancel")
async def admin_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.answer("Действие отменено." if callback.data == "admin:cancel" else "Админ-панель")
        await show_panel(callback.message)


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    count = await db.count_users()
    groups = await db.count_groups()
    channels = await db.get_channels()
    await callback.answer()
    await callback.message.answer(
        f"📊 Пользователей: <b>{count}</b>\nГрупп: <b>{groups}</b>\nОбязательных каналов: <b>{len(channels)}</b>"
    )


@router.callback_query(F.data == "admin:list_sub")
async def list_subs(callback: CallbackQuery) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    channels = await db.get_channels()
    await callback.answer()
    if not channels:
        await callback.message.answer("Обязательных подписок пока нет.")
        return
    lines = ["📋 <b>Обязательные подписки</b>\n"]
    for channel in channels:
        uname = f" @{channel['username']}" if channel.get("username") else ""
        lines.append(f"• {channel['title']}{uname}\n<code>{channel['chat_id']}</code>")
    await callback.message.answer("\n".join(lines))


@router.callback_query(F.data == "admin:add_sub")
async def add_sub_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.add_channel)
    await callback.answer()
    await callback.message.answer(
        "Пришли @username канала, ссылку t.me/... или перешли пост из канала.\n\n"
        "Бот должен быть <b>админом</b> в этом канале, иначе проверка подписки не сработает.",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(AdminStates.add_channel)
async def add_sub_save(message: Message, state: FSMContext) -> None:
    if not admin_only(message.from_user.id if message.from_user else None):
        return

    chat_ref = None
    if message.forward_from_chat:
        chat_ref = message.forward_from_chat.id
    elif message.text:
        text = message.text.strip()
        if text.startswith("@"):
            chat_ref = text
        elif "t.me/" in text:
            slug = text.split("t.me/")[-1].split("?")[0].strip("/")
            if slug.startswith("+") or slug.startswith("joinchat/"):
                await message.answer(
                    "Для приватного канала перешли пост из него, "
                    "а бота добавь туда администратором."
                )
                return
            chat_ref = f"@{slug}"
        elif text.lstrip("-").isdigit():
            chat_ref = int(text)

    if chat_ref is None:
        await message.answer("Не понял канал. Пришли @username или перешли пост.")
        return

    try:
        chat = await message.bot.get_chat(chat_ref)
        me = await message.bot.get_me()
        member = await message.bot.get_chat_member(chat.id, me.id)
        if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            await message.answer("Сначала добавь бота администратором в этот канал.")
            return
        if chat.username:
            invite_link = f"https://t.me/{chat.username}"
        else:
            try:
                invite_link = await message.bot.export_chat_invite_link(chat.id)
            except (TelegramBadRequest, TelegramForbiddenError):
                invite_link = chat.invite_link
        if not invite_link:
            await message.answer(
                "Не удалось получить ссылку на канал. Выдай боту право создавать инвайт-ссылки."
            )
            return
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer(
            "Не удалось открыть канал. Проверь, что бот добавлен админом и ссылка верная."
        )
        return

    await db.add_channel(
        chat_id=chat.id,
        title=chat.title or chat.username or str(chat.id),
        username=chat.username,
        invite_link=invite_link,
    )
    await state.clear()
    await message.answer(f"Подписка добавлена: <b>{chat.title or chat.username}</b>")
    await show_panel(message)


@router.callback_query(F.data == "admin:del_sub")
async def del_sub_start(callback: CallbackQuery) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    channels = await db.get_channels()
    await callback.answer()
    if not channels:
        await callback.message.answer("Удалять нечего — список пуст.")
        return
    await callback.message.answer(
        "Выбери канал, который нужно убрать из обязательных:",
        reply_markup=keyboards.delete_channels_keyboard(channels),
    )


@router.callback_query(F.data.startswith("admin:rm:"))
async def del_sub_confirm(callback: CallbackQuery) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    channel_id = int(callback.data.split(":")[-1])
    channel = await db.get_channel(channel_id)
    deleted = await db.delete_channel(channel_id)
    await callback.answer("Удалено" if deleted else "Уже нет")
    title = channel["title"] if channel else "канал"
    if callback.message:
        await callback.message.edit_text(f"Подписка «{title}» удалена.")
        await show_panel(callback.message)


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.wait_broadcast)
    await callback.answer()
    await callback.message.answer(
        "Пришли пост для рассылки: текст, фото, видео или любой другой пост. "
        "Я отправлю его всем пользователям бота.",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(AdminStates.wait_broadcast)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    if not admin_only(message.from_user.id if message.from_user else None):
        return
    await state.update_data(from_chat=message.chat.id, message_id=message.message_id)
    await state.set_state(AdminStates.confirm_broadcast)
    users = await db.count_users()
    groups = await db.count_groups()
    await message.answer(
        f"Разослать этот пост <b>{users}</b> пользователям и <b>{groups}</b> группам?",
        reply_markup=keyboards.broadcast_confirm_keyboard(),
    )


@router.callback_query(AdminStates.confirm_broadcast, F.data == "admin:bc_yes")
async def broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
    if not admin_only(callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    await state.clear()
    await callback.answer("Рассылка запущена")
    chat_ids = await db.all_broadcast_chats()
    ok = 0
    fail = 0
    from_chat = data["from_chat"]
    message_id = data["message_id"]
    status = await callback.message.answer(f"Рассылаю… 0/{len(chat_ids)}")

    for index, chat_id in enumerate(chat_ids, start=1):
        try:
            await callback.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat,
                message_id=message_id,
            )
            ok += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            try:
                await callback.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=from_chat,
                    message_id=message_id,
                )
                ok += 1
            except Exception:
                fail += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            fail += 1
        except Exception:
            log.exception("Broadcast failed for %s", chat_id)
            fail += 1
        if index % 20 == 0:
            try:
                await status.edit_text(f"Рассылаю… {index}/{len(chat_ids)}")
            except TelegramBadRequest:
                pass
        await asyncio.sleep(0.05)

    await status.edit_text(f"Готово. Доставлено: <b>{ok}</b>, ошибок: <b>{fail}</b>.")
    await show_panel(callback.message)


@router.message(StateFilter(AdminStates.add_channel, AdminStates.wait_broadcast, AdminStates.confirm_broadcast))
async def ignore_other_while_admin(message: Message) -> None:
    if admin_only(message.from_user.id if message.from_user else None):
        await message.answer("Сначала закончи действие в админке или нажми «Отмена».")
