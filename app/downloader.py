from __future__ import annotations

import asyncio
import mimetypes
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
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
class DownloadResult:
    kind: str  # "video" | "photos"
    title: str
    source: str
    path: Path | None = None
    photos: list[Path] = field(default_factory=list)

    def cleanup(self) -> None:
        for photo in self.photos:
            photo.unlink(missing_ok=True)
        if self.path:
            self.path.unlink(missing_ok=True)


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


def _find_photos(info: dict) -> list[str]:
    """Собрать прямые ссылки на кадры TikTok-слайдшоу."""
    candidates: list[str] = []
    if isinstance(info.get("thumbnails"), list):
        for thumb in info["thumbnails"]:
            if thumb.get("url"):
                candidates.append(thumb["url"])
    if info.get("thumbnail"):
        candidates.append(info["thumbnail"])

    unique: list[str] = []
    seen = set()
    for url in candidates:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _download_sync(url: str, dest_dir: Path) -> DownloadResult:
    dest_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    opts = _ydl_opts(str(dest_dir / f"{job_id}.%(ext)s"))

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

    title = (info.get("title") or "video").strip() or "video"
    source = _source_name(url)

    path = Path(filename)
    if not path.exists():
        mp4 = path.with_suffix(".mp4")
        if mp4.exists():
            path = mp4

    if path.exists() and path.stat().st_size > 0:
        size = path.stat().st_size
        if size > TELEGRAM_MAX_BYTES:
            path.unlink(missing_ok=True)
            raise DownloadError(
                "Видео слишком большое для Telegram (лимит бота — 50 МБ). "
                "Попробуйте другое видео или более короткое."
            )
        return DownloadResult(kind="video", title=title[:200], source=source, path=path)

    # Если видео нет — пробуем TikTok-слайдшоу (фото).
    photo_urls = _find_photos(info)
    if photo_urls:
        return DownloadResult(kind="photos", title=title[:200], source=source), photo_urls

    raise DownloadError("Файл после скачивания не найден.")


async def _download_photos(urls: list[str], dest_dir: Path) -> list[Path]:
    photos: list[Path] = []
    async with aiohttp.ClientSession() as session:
        for index, url in enumerate(urls, start=1):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.read()
                    if not data:
                        continue
                    ext = Path(url.split("?")[0]).suffix or mimetypes.guess_extension(
                        resp.headers.get("Content-Type", "")
                    ) or ".jpg"
                    photo_path = dest_dir / f"{uuid.uuid4().hex}_{index}{ext}"
                    photo_path.write_bytes(data)
                    photos.append(photo_path)
            except Exception:
                continue
    return photos


async def download_video(url: str) -> DownloadResult:
    result, photo_urls = await asyncio.to_thread(_download_sync, url, DOWNLOAD_DIR)
    if result.kind == "photos" and photo_urls:
        photos = await _download_photos(photo_urls, DOWNLOAD_DIR)
        if not photos:
            raise DownloadError("Не удалось скачать фото.")
        result.photos = photos
    return result
