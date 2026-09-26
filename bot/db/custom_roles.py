"""Свої ролі, створені адміністраторами чату."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

MAX_PER_CHAT = 10
EDITABLE = ("name", "description", "team", "ability", "min_players", "enabled")


@dataclass
class CustomRole:
    id: int
    chat_id: int
    name: str
    description: str
    team: str
    ability: str
    min_players: int
    enabled: bool

    @property
    def key(self) -> str:
        return f"c{self.id}"

    def to_engine(self) -> dict:
        """Словник для рушія гри (зберігається в налаштуваннях гри і снапшоті)."""
        return {"key": self.key, "name": self.name, "team": self.team, "ability": self.ability,
                "min_players": self.min_players, "description": self.description}


def _row(r: asyncpg.Record) -> CustomRole:
    return CustomRole(**{k: r[k] for k in CustomRole.__dataclass_fields__})


async def list_for_chat(pool: asyncpg.Pool, chat_id: int) -> list[CustomRole]:
    rows = await pool.fetch("SELECT * FROM custom_roles WHERE chat_id = $1 ORDER BY id", chat_id)
    return [_row(r) for r in rows]


async def get(pool: asyncpg.Pool, role_id: int) -> CustomRole | None:
    r = await pool.fetchrow("SELECT * FROM custom_roles WHERE id = $1", role_id)
    return _row(r) if r else None


async def create(pool: asyncpg.Pool, chat_id: int, name: str, created_by: int) -> CustomRole | str:
    """Нова роль або код помилки: 'limit' | 'exists'."""
    async with pool.acquire() as conn, conn.transaction():
        # Блокування по чату, щоб паралельні створення не обійшли ліміт.
        await conn.execute("SELECT pg_advisory_xact_lock($1)", chat_id)
        if await conn.fetchval("SELECT count(*) FROM custom_roles WHERE chat_id = $1", chat_id) >= MAX_PER_CHAT:
            return "limit"
        try:
            r = await conn.fetchrow(
                "INSERT INTO custom_roles (chat_id, name, created_by) VALUES ($1, $2, $3) RETURNING *",
                chat_id, name, created_by,
            )
        except asyncpg.UniqueViolationError:
            return "exists"
    return _row(r)


async def update(pool: asyncpg.Pool, role_id: int, field: str, value) -> bool:
    """False, якщо така назва в чаті вже є."""
    if field not in EDITABLE:
        raise ValueError(field)
    try:
        await pool.execute(f"UPDATE custom_roles SET {field} = $2 WHERE id = $1", role_id, value)
    except asyncpg.UniqueViolationError:
        return False
    return True


async def delete(pool: asyncpg.Pool, role_id: int) -> None:
    await pool.execute("DELETE FROM custom_roles WHERE id = $1", role_id)
