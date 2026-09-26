"""Гравці: профіль, баланси, VIP, щоденний бонус."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg

CURRENCIES = ("shagy", "chervintsi")


@dataclass
class User:
    id: int
    name: str
    username: str | None
    shagy: int
    chervintsi: int
    vip_until: datetime | None
    daily_at: datetime | None
    blocked: bool
    games: int
    wins: int

    @property
    def is_vip(self) -> bool:
        return self.vip_until is not None and self.vip_until > datetime.now(UTC)


def _row(r: asyncpg.Record | None) -> User | None:
    if r is None:
        return None
    return User(
        id=r["id"], name=r["name"], username=r["username"], shagy=r["shagy"],
        chervintsi=r["chervintsi"], vip_until=r["vip_until"], daily_at=r["daily_at"],
        blocked=r["blocked"], games=r["games"], wins=r["wins"],
    )


async def upsert(pool: asyncpg.Pool, user_id: int, name: str, username: str | None) -> User:
    r = await pool.fetchrow(
        "INSERT INTO users (id, name, username) VALUES ($1, $2, $3) "
        "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, username = EXCLUDED.username "
        "RETURNING *",
        user_id, name, username,
    )
    return _row(r)


async def get(pool: asyncpg.Pool, user_id: int) -> User | None:
    return _row(await pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id))


async def add_balance(pool: asyncpg.Pool | asyncpg.Connection, user_id: int, currency: str, amount: int) -> int | None:
    """Змінює баланс; повертає новий баланс або None, якщо коштів не вистачає / гравця немає."""
    if currency not in CURRENCIES:
        raise ValueError(currency)
    return await pool.fetchval(
        f"UPDATE users SET {currency} = {currency} + $2 "
        f"WHERE id = $1 AND {currency} + $2 >= 0 RETURNING {currency}",
        user_id, amount,
    )


async def extend_vip(pool: asyncpg.Pool | asyncpg.Connection, user_id: int, days: int) -> datetime | None:
    return await pool.fetchval(
        "UPDATE users SET vip_until = GREATEST(COALESCE(vip_until, now()), now()) + make_interval(days => $2) "
        "WHERE id = $1 RETURNING vip_until",
        user_id, days,
    )


async def revoke_vip_days(pool: asyncpg.Pool | asyncpg.Connection, user_id: int, days: int) -> None:
    await pool.execute(
        "UPDATE users SET vip_until = vip_until - make_interval(days => $2) WHERE id = $1 AND vip_until IS NOT NULL",
        user_id, days,
    )


async def claim_daily(pool: asyncpg.Pool, user_id: int, amount: int, cooldown: timedelta) -> tuple[bool, datetime | None]:
    """Повертає (успіх, коли_можна_наступного_разу)."""
    r = await pool.fetchrow(
        "UPDATE users SET shagy = shagy + $2, daily_at = now() "
        "WHERE id = $1 AND (daily_at IS NULL OR daily_at <= now() - $3::interval) RETURNING daily_at",
        user_id, amount, cooldown,
    )
    if r is not None:
        return True, r["daily_at"] + cooldown
    last = await pool.fetchval("SELECT daily_at FROM users WHERE id = $1", user_id)
    return False, (last + cooldown) if last else None


async def set_blocked(pool: asyncpg.Pool, user_id: int, blocked: bool) -> bool:
    res = await pool.execute("UPDATE users SET blocked = $2 WHERE id = $1", user_id, blocked)
    return res.endswith(" 1")


async def all_ids(pool: asyncpg.Pool) -> list[int]:
    return [r["id"] for r in await pool.fetch("SELECT id FROM users WHERE NOT blocked")]


async def stats(pool: asyncpg.Pool) -> dict[str, int]:
    r = await pool.fetchrow(
        "SELECT (SELECT count(*) FROM users) AS users,"
        " (SELECT count(*) FROM users WHERE vip_until > now()) AS vips,"
        " (SELECT count(*) FROM game_results) AS games,"
        " (SELECT count(*) FROM game_results WHERE created_at > now() - interval '1 day') AS games_day,"
        " (SELECT COALESCE(sum(stars), 0) FROM purchases WHERE NOT refunded) AS stars"
    )
    return dict(r)
