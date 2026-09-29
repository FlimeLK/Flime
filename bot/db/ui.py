"""Налаштування оформлення: перевизначені емодзі та медіа для сцен."""

from __future__ import annotations

import asyncpg


async def emoji_overrides(pool: asyncpg.Pool) -> dict[str, str]:
    return {r["key"]: r["custom_id"] for r in await pool.fetch("SELECT key, custom_id FROM emoji_overrides")}


async def set_emoji(pool: asyncpg.Pool, key: str, custom_id: str | None) -> None:
    if custom_id:
        await pool.execute(
            "INSERT INTO emoji_overrides (key, custom_id) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET custom_id = EXCLUDED.custom_id",
            key, custom_id,
        )
    else:
        await pool.execute("DELETE FROM emoji_overrides WHERE key = $1", key)


async def media_all(pool: asyncpg.Pool) -> dict[str, tuple[str, str]]:
    return {r["slot"]: (r["kind"], r["file_id"]) for r in await pool.fetch("SELECT * FROM media")}


async def set_media(pool: asyncpg.Pool, slot: str, kind: str | None, file_id: str | None) -> None:
    if kind and file_id:
        await pool.execute(
            "INSERT INTO media (slot, kind, file_id) VALUES ($1, $2, $3) "
            "ON CONFLICT (slot) DO UPDATE SET kind = EXCLUDED.kind, file_id = EXCLUDED.file_id",
            slot, kind, file_id,
        )
    else:
        await pool.execute("DELETE FROM media WHERE slot = $1", slot)
