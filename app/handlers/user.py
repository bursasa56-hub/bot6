from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    FSInputFile,
    InputMediaPhoto,
    Message,
)

from app import db, keyboards
from app.downloader import (
    DownloadError,
    download_video,
    extract_url,
    is_supported_url,
)
from app.subscriptions import missing_channels

router = Router()
busy_users: set[int] = set()
busy_lock = asyncio.Lock()


HELP_TEXT = (
    "Отправь ссылку на видео из <b>TikTok</b> или <b>YouTube</b> — "
    "я скачаю его без водяного знака и пришлю сюда.\n\n"
    "Поддерживаются обычные ролики, Shorts и TikTok."
)


async def require_subscriptions(message: Message) -> bool:
    user = message.from_user
    if user is None:
        return False
    missing = await missing_channels(message.bot, user.id)
    if not missing:
        return True
    await message.answer(
        "Чтобы пользоваться ботом, подпишись на каналы ниже и нажми «Я подписался».",
        reply_markup=keyboards.subscribe_keyboard(missing),
    )
    return False


def _is_group_chat(message: Message) -> bool:
    return message.chat.type in {"group", "supergroup"}


async def _save_chat(message: Message) -> None:
    if _is_group_chat(message):
        await db.upsert_group(message.chat.id, message.chat.title)
    elif message.from_user:
        await db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    await _save_chat(message)
    bot_info = await message.bot.get_me()
    await message.answer(
        "Привет! Пришли ссылку на видео из TikTok или YouTube — скачаю без водяного знака.\n\n"
        "Меня можно добавить в группу кнопкой ниже.",
        reply_markup=keyboards.main_menu(user.id),
    )
    await message.answer(
        "Добавить бота в группу:",
        reply_markup=keyboards.add_to_group_keyboard(bot_info.username),
    )
    await require_subscriptions(message)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    await message.answer(f"Твой Telegram ID: <code>{user.id}</code>")


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def help_button(message: Message) -> None:
    if not await require_subscriptions(message):
        return
    await message.answer(HELP_TEXT)


@router.callback_query(F.data == "check_subs")
async def check_subs(callback: CallbackQuery) -> None:
    user = callback.from_user
    if callback.message is None:
        return
    missing = await missing_channels(callback.bot, user.id)
    if missing:
        await callback.answer("Подписки ещё нет на все каналы.", show_alert=True)
        await callback.message.edit_text(
            "Чтобы пользоваться ботом, подпишись на каналы ниже и нажми «Я подписался».",
            reply_markup=keyboards.subscribe_keyboard(missing),
        )
        return
    await callback.answer("Готово!")
    await callback.message.edit_text(
        "Подписки проверены. Теперь отправь ссылку на видео."
    )


@router.my_chat_member()
async def my_chat_member(update: ChatMemberUpdated) -> None:
    chat = update.chat
    if chat.type not in {"group", "supergroup"}:
        return
    status = update.new_chat_member.status
    if status in {"member", "administrator"}:
        await db.upsert_group(chat.id, chat.title)
    elif status in {"left", "kicked"}:
        await db.remove_broadcast_chat(chat.id)


@router.message(F.text)
async def handle_link(message: Message) -> None:
    user = message.from_user
    if user is None or not message.text:
        return
    if message.text.startswith("/") or message.text in {"❓ Помощь", "⚙️ Админ-панель"}:
        return

    await _save_chat(message)

    url = extract_url(message.text)
    if url is None:
        if not _is_group_chat(message):
            await message.answer("Пришли ссылку на видео из TikTok или YouTube.")
        return
    if not await require_subscriptions(message):
        return
    if not is_supported_url(url):
        if not _is_group_chat(message):
            await message.answer("Пока умею скачивать только TikTok и YouTube.")
        return

    async with busy_lock:
        if user.id in busy_users:
            await message.answer("Подожди, предыдущее видео ещё качается.")
            return
        busy_users.add(user.id)

    status = await message.answer("Скачиваю, это может занять минуту…")
    try:
        result = await download_video(url)
        try:
            if result.kind == "photos" and result.photos:
                media = [
                    InputMediaPhoto(media=FSInputFile(photo))
                    for photo in result.photos[:10]
                ]
                if media:
                    media[0].caption = f"{result.source}: {escape(result.title)}"
                await message.answer_media_group(media=media)
                await status.delete()
            elif result.kind == "video" and result.path:
                caption = f"{result.source}: {escape(result.title)}"
                filename = f"{result.source}.mp4"
                try:
                    await message.answer_video(
                        video=FSInputFile(result.path, filename=filename),
                        caption=caption,
                        supports_streaming=True,
                    )
                except Exception:
                    await message.answer_document(
                        document=FSInputFile(result.path, filename=filename),
                        caption=caption,
                    )
                await status.delete()
            else:
                await status.edit_text("Не удалось получить контент по ссылке.")
        finally:
            result.cleanup()
    except DownloadError as exc:
        await status.edit_text(str(exc))
    except Exception:
        await status.edit_text("Не получилось отправить контент. Попробуй другую ссылку.")
    finally:
        async with busy_lock:
            busy_users.discard(user.id)
