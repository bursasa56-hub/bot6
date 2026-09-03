from __future__ import annotations

from typing import Any

import aiosqlite

from app.config import DB_PATH

CHAT_TYPE_USER = "user"
CHAT_TYPE_GROUP = "group"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                username TEXT,
                invite_link TEXT
            );

            CREATE TABLE IF NOT EXISTS broadcast_chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL DEFAULT 'user',
                title TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await _seed_broadcast_chats(db)
        await db.commit()


async def _seed_broadcast_chats(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        INSERT INTO broadcast_chats (chat_id, chat_type, title)
        SELECT user_id, 'user', COALESCE(username, full_name)
        FROM users
        WHERE user_id NOT IN (SELECT chat_id FROM broadcast_chats)
        """
    )


async def upsert_user(user_id: int, username: str | None, full_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name
            """,
            (user_id, username, full_name),
        )
        await db.execute(
            """
            INSERT INTO broadcast_chats (chat_id, chat_type, title)
            VALUES (?, 'user', ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type = excluded.chat_type,
                title = excluded.title
            """,
            (user_id, CHAT_TYPE_USER, username or full_name),
        )
        await db.commit()


async def upsert_group(chat_id: int, title: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO broadcast_chats (chat_id, chat_type, title)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type = excluded.chat_type,
                title = excluded.title
            """,
            (chat_id, CHAT_TYPE_GROUP, title),
        )
        await db.commit()


async def remove_broadcast_chat(chat_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM broadcast_chats WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0


async def count_groups() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM broadcast_chats WHERE chat_type = ?",
            (CHAT_TYPE_GROUP,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0


async def all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]


async def all_broadcast_chats() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM broadcast_chats") as cursor:
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]


async def add_channel(
    chat_id: int,
    title: str,
    username: str | None,
    invite_link: str | None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO channels (chat_id, title, username, invite_link)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username,
                invite_link = excluded.invite_link
            """,
            (chat_id, title, username, invite_link),
        )
        await db.commit()


async def delete_channel(channel_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_channels() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, chat_id, title, username, invite_link FROM channels ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_channel(channel_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, chat_id, title, username, invite_link FROM channels WHERE id = ?",
            (channel_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
