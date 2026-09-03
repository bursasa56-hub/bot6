from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.config import DOWNLOAD_DIR, TELEGRAM_MAX_BYTES

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

SUPPORTED_HOSTS = (
    "tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
)


class DownloadError(Exception):
    pass


@dataclass
class DownloadedVideo:
    path: Path
    title: str
    source: str


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(").,]>\"'") if match else None


def is_supported_url(url: str) -> bool:
    lowered = url.lower()
    return any(host in lowered for host in SUPPORTED_HOSTS)


def _source_name(url: str) -> str:
    lowered = url.lower()
    if "tiktok" in lowered:
        return "TikTok"
    if "youtu" in lowered:
        return "YouTube"
    return "видео"


def _ydl_opts(outtmpl: str) -> dict:
    return {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 3,
        "merge_output_format": "mp4",
        "restrictfilenames": True,
        "format": (
            "bestvideo[ext=mp4][height<=720][filesize<48M]+bestaudio[ext=m4a]/"
            "bestvideo[height<=720][filesize<48M]+bestaudio/"
            "best[ext=mp4][height<=720][filesize<48M]/"
            "best[height<=720][filesize<48M]/"
            "best[ext=mp4][filesize<48M]/"
            "best[filesize<48M]/"
            "bv*+ba/b"
        ),
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        },
    }


def _download_sync(url: str, dest_dir: Path) -> DownloadedVideo:
    dest_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_dir / f"{uuid.uuid4().hex}.%(ext)s")
    opts = _ydl_opts(outtmpl)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise DownloadError("Не удалось получить информацию о видео.")
            if "entries" in info:
                entries = [item for item in (info.get("entries") or []) if item]
                if not entries:
                    raise DownloadError("По ссылке нет видео.")
                info = entries[0]
            filename = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_human_error(str(exc))) from exc

    path = Path(filename)
    if not path.exists():
        mp4 = path.with_suffix(".mp4")
        if mp4.exists():
            path = mp4
        else:
            raise DownloadError("Файл после скачивания не найден.")

    size = path.stat().st_size
    if size <= 0:
        path.unlink(missing_ok=True)
        raise DownloadError("Получен пустой файл.")
    if size > TELEGRAM_MAX_BYTES:
        path.unlink(missing_ok=True)
        raise DownloadError(
            "Видео слишком большое для Telegram (лимит бота — 50 МБ). "
            "Попробуйте другое видео или более короткое."
        )

    title = (info.get("title") or "video").strip() or "video"
    return DownloadedVideo(path=path, title=title[:200], source=_source_name(url))


def _human_error(raw: str) -> str:
    text = raw.lower()
    if "private" in text or "login" in text or "sign in" in text:
        return "Видео недоступно без авторизации или скрыто."
    if "unavailable" in text or "not available" in text:
        return "Видео недоступно. Проверьте ссылку."
    if "copyright" in text or "removed" in text:
        return "Видео удалено или заблокировано."
    return "Не удалось скачать видео. Проверьте ссылку и попробуйте ещё раз."


async def download_video(url: str) -> DownloadedVideo:
    return await asyncio.to_thread(_download_sync, url, DOWNLOAD_DIR)
