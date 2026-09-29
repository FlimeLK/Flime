"""Власні ролі чату."""

from __future__ import annotations

import asyncpg

MAX_PER_CHAT = 10
FIELDS = "id, chat_id, name, emoji, emoji_id, description, team, ability, min_players, enabled"


async def list_for_chat(pool: asyncpg.Pool, chat_id: int, enabled_only: bool = False) -> list[dict]:
    query = f"SELECT {FIELDS} FROM custom_roles WHERE chat_id = $1"
    if enabled_only:
        query += " AND enabled"
    return [dict(r) for r in await pool.fetch(query + " ORDER BY id", chat_id)]


async def get(pool: asyncpg.Pool, role_id: int) -> dict | None:
    r = await pool.fetchrow(f"SELECT {FIELDS} FROM custom_roles WHERE id = $1", role_id)
    return dict(r) if r else None


async def count(pool: asyncpg.Pool, chat_id: int) -> int:
    return await pool.fetchval("SELECT count(*) FROM custom_roles WHERE chat_id = $1", chat_id)


async def create(pool: asyncpg.Pool, chat_id: int, created_by: int, *, name: str, emoji: str,
                 emoji_id: str | None, description: str, team: str, ability: str, min_players: int) -> int:
    return await pool.fetchval(
        "INSERT INTO custom_roles (chat_id, created_by, name, emoji, emoji_id, description, team, ability, "
        "min_players) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id",
        chat_id, created_by, name, emoji, emoji_id, description, team, ability, min_players,
    )


async def toggle(pool: asyncpg.Pool, role_id: int) -> bool | None:
    return await pool.fetchval(
        "UPDATE custom_roles SET enabled = NOT enabled WHERE id = $1 RETURNING enabled", role_id)


async def delete(pool: asyncpg.Pool, role_id: int) -> bool:
    res = await pool.execute("DELETE FROM custom_roles WHERE id = $1", role_id)
    return res.endswith(" 1")
