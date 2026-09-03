from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

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


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    await db.upsert_user(user.id, user.username, user.full_name)
    await message.answer(
        "Привет! Пришли ссылку на видео из TikTok или YouTube — скачаю без водяного знака.",
        reply_markup=keyboards.main_menu(user.id),
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


@router.message(F.text)
async def handle_link(message: Message) -> None:
    user = message.from_user
    if user is None or not message.text:
        return
    if message.text.startswith("/") or message.text in {"❓ Помощь", "⚙️ Админ-панель"}:
        return

    await db.upsert_user(user.id, user.username, user.full_name)
    if not await require_subscriptions(message):
        return

    url = extract_url(message.text)
    if url is None:
        await message.answer("Пришли ссылку на видео из TikTok или YouTube.")
        return
    if not is_supported_url(url):
        await message.answer("Пока умею скачивать только TikTok и YouTube.")
        return

    async with busy_lock:
        if user.id in busy_users:
            await message.answer("Подожди, предыдущее видео ещё качается.")
            return
        busy_users.add(user.id)

    status = await message.answer("Скачиваю видео, это может занять минуту…")
    try:
        video = await download_video(url)
        caption = f"{video.source}: {escape(video.title)}"
        filename = f"{video.source}.mp4"
        try:
            try:
                await message.answer_video(
                    video=FSInputFile(video.path, filename=filename),
                    caption=caption,
                    supports_streaming=True,
                )
            except Exception:
                await message.answer_document(
                    document=FSInputFile(video.path, filename=filename),
                    caption=caption,
                )
        finally:
            video.path.unlink(missing_ok=True)
        try:
            await status.delete()
        except Exception:
            pass
    except DownloadError as exc:
        await status.edit_text(str(exc))
    except Exception:
        await status.edit_text("Не получилось отправить видео. Попробуй другую ссылку.")
    finally:
        async with busy_lock:
            busy_users.discard(user.id)
