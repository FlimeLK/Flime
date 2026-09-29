"""Інвентар предметів."""

from __future__ import annotations

import asyncpg

from bot.db import users


async def inventory(pool: asyncpg.Pool, user_id: int) -> dict[str, int]:
    rows = await pool.fetch("SELECT item, qty FROM inventory WHERE user_id = $1 AND qty > 0", user_id)
    return {r["item"]: r["qty"] for r in rows}


async def buy(pool: asyncpg.Pool, user_id: int, item: str, price: int) -> int | None:
    """Списує ліри й додає предмет. Повертає новий баланс або None, якщо не вистачає."""
    async with pool.acquire() as conn, conn.transaction():
        balance = await users.add_balance(conn, user_id, "shagy", -price)
        if balance is None:
            return None
        await add_item(conn, user_id, item, 1)
        return balance


async def add_item(conn: asyncpg.Pool | asyncpg.Connection, user_id: int, item: str, qty: int) -> None:
    await conn.execute(
        "INSERT INTO inventory (user_id, item, qty) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id, item) DO UPDATE SET qty = inventory.qty + EXCLUDED.qty",
        user_id, item, qty,
    )


async def take_for_game(pool: asyncpg.Pool, user_id: int, slots: int, order: list[str]) -> list[str]:
    """Бере в «кишеню» до `slots` різних предметів (по одному кожного) і списує їх з інвентарю."""
    taken: list[str] = []
    async with pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            "SELECT item FROM inventory WHERE user_id = $1 AND qty > 0 FOR UPDATE", user_id
        )
        owned = {r["item"] for r in rows}
        for item in order:
            if len(taken) >= slots:
                break
            if item in owned:
                await conn.execute(
                    "UPDATE inventory SET qty = qty - 1 WHERE user_id = $1 AND item = $2", user_id, item
                )
                taken.append(item)
    return taken


async def return_items(pool: asyncpg.Pool, user_id: int, items: list[str]) -> None:
    async with pool.acquire() as conn, conn.transaction():
        for item in items:
            await add_item(conn, user_id, item, 1)
