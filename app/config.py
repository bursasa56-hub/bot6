import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(item.strip())
    for item in os.getenv("ADMIN_IDS", "").split(",")
    if item.strip().lstrip("-").isdigit()
}

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
DB_PATH = DATA_DIR / "bot.db"
DOWNLOAD_DIR = DATA_DIR / "downloads"
TELEGRAM_MAX_BYTES = 49 * 1024 * 1024


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
