"""Промокоди."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from bot.db import users


@dataclass
class Reward:
    shagy: int
    chervintsi: int
    vip_days: int


async def create(pool: asyncpg.Pool, code: str, shagy: int, chervintsi: int, vip_days: int, max_uses: int) -> bool:
    res = await pool.execute(
        "INSERT INTO promocodes (code, shagy, chervintsi, vip_days, max_uses) VALUES ($1, $2, $3, $4, $5) "
        "ON CONFLICT (code) DO NOTHING",
        code.upper(), shagy, chervintsi, vip_days, max_uses,
    )
    return res.endswith(" 1")


async def delete(pool: asyncpg.Pool, code: str) -> bool:
    res = await pool.execute("DELETE FROM promocodes WHERE code = $1", code.upper())
    return res.endswith(" 1")


async def list_all(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT * FROM promocodes ORDER BY created_at DESC LIMIT 50")


async def activate(pool: asyncpg.Pool, code: str, user_id: int) -> Reward | str:
    """Повертає нагороду або код помилки: 'not_found', 'used', 'exhausted'."""
    code = code.upper()
    async with pool.acquire() as conn, conn.transaction():
        promo = await conn.fetchrow("SELECT * FROM promocodes WHERE code = $1 FOR UPDATE", code)
        if promo is None:
            return "not_found"
        if await conn.fetchval(
            "SELECT 1 FROM promocode_uses WHERE code = $1 AND user_id = $2", code, user_id
        ):
            return "used"
        if promo["uses"] >= promo["max_uses"]:
            return "exhausted"
        await conn.execute("INSERT INTO promocode_uses (code, user_id) VALUES ($1, $2)", code, user_id)
        await conn.execute("UPDATE promocodes SET uses = uses + 1 WHERE code = $1", code)
        if promo["shagy"]:
            await users.add_balance(conn, user_id, "shagy", promo["shagy"])
        if promo["chervintsi"]:
            await users.add_balance(conn, user_id, "chervintsi", promo["chervintsi"])
        if promo["vip_days"]:
            await users.extend_vip(conn, user_id, promo["vip_days"])
        return Reward(promo["shagy"], promo["chervintsi"], promo["vip_days"])
