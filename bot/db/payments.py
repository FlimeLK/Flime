"""Оплати зірками Telegram."""

from __future__ import annotations

import asyncpg


async def record(pool: asyncpg.Pool | asyncpg.Connection, user_id: int, product: str, stars: int, charge_id: str) -> bool:
    """Записує покупку. False, якщо цей платіж уже оброблено (повторний апдейт)."""
    res = await pool.execute(
        "INSERT INTO purchases (user_id, product, stars, charge_id) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (charge_id) DO NOTHING",
        user_id, product, stars, charge_id,
    )
    return res.endswith(" 1")


async def get(pool: asyncpg.Pool, charge_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM purchases WHERE charge_id = $1", charge_id)


async def mark_refunded(pool: asyncpg.Pool | asyncpg.Connection, charge_id: str) -> bool:
    res = await pool.execute(
        "UPDATE purchases SET refunded = TRUE WHERE charge_id = $1 AND NOT refunded", charge_id
    )
    return res.endswith(" 1")


async def recent(pool: asyncpg.Pool, limit: int = 15) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT * FROM purchases ORDER BY created_at DESC LIMIT $1", limit)


async def get_by_id(pool: asyncpg.Pool, purchase_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM purchases WHERE id = $1", purchase_id)
