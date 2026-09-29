"""Налаштування гри для кожного чату."""

from __future__ import annotations

from dataclasses import dataclass, field

import asyncpg

from bot.engine.models import MAX_PLAYERS, MIN_PLAYERS
from bot.engine.setup import MAFIA_RATIOS as RATIOS

# Поле → (мінімум, максимум, крок) у секундах.
TIMER_LIMITS: dict[str, tuple[int, int, int]] = {
    "reg_time": (30, 300, 15),
    "night_time": (30, 180, 15),
    "day_time": (15, 300, 15),
    "vote_time": (20, 120, 5),
    "confirm_time": (15, 90, 5),
}
TOGGLES = ("hide_dead_roles", "secret_vote", "items_enabled", "omerta_dead", "omerta_night",
           "pin_lobby", "start_admins_only")
# Межі кількості гравців: поле → (мінімум, максимум, крок).
PLAYER_LIMITS: dict[str, tuple[int, int, int]] = {
    "min_players": (MIN_PLAYERS, 10, 1),
    "max_players": (6, MAX_PLAYERS, 2),
}
MAFIA_RATIOS = tuple(RATIOS)


@dataclass
class GroupSettings:
    chat_id: int
    title: str = ""
    reg_time: int = 90
    night_time: int = 60
    day_time: int = 60
    vote_time: int = 45
    confirm_time: int = 30
    disabled_roles: list[str] = field(default_factory=list)
    hide_dead_roles: bool = False
    secret_vote: bool = False
    items_enabled: bool = True
    omerta_dead: bool = False
    omerta_night: bool = False
    mafia_ratio: str = "normal"
    min_players: int = MIN_PLAYERS
    max_players: int = MAX_PLAYERS
    disabled_items: list[str] = field(default_factory=list)
    pin_lobby: bool = False
    start_admins_only: bool = False

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> GroupSettings:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


async def get(pool: asyncpg.Pool, chat_id: int, title: str = "") -> GroupSettings:
    r = await pool.fetchrow(
        "INSERT INTO group_settings (chat_id, title) VALUES ($1, $2) "
        "ON CONFLICT (chat_id) DO UPDATE SET title = CASE WHEN $2 = '' THEN group_settings.title ELSE $2 END "
        "RETURNING *",
        chat_id, title,
    )
    return GroupSettings.from_dict({**dict(r), "disabled_roles": list(r["disabled_roles"]),
                                    "disabled_items": list(r["disabled_items"])})


async def set_timer(pool: asyncpg.Pool, chat_id: int, name: str, value: int) -> int:
    lo, hi, _ = TIMER_LIMITS[name]
    value = max(lo, min(hi, value))
    await pool.execute(f"UPDATE group_settings SET {name} = $2 WHERE chat_id = $1", chat_id, value)
    return value


async def toggle(pool: asyncpg.Pool, chat_id: int, name: str) -> bool:
    if name not in TOGGLES:
        raise ValueError(name)
    return await pool.fetchval(
        f"UPDATE group_settings SET {name} = NOT {name} WHERE chat_id = $1 RETURNING {name}", chat_id
    )


async def toggle_role(pool: asyncpg.Pool, chat_id: int, role: str) -> bool:
    """Вмикає/вимикає роль; повертає True, якщо роль тепер увімкнена."""
    disabled = await pool.fetchval(
        "UPDATE group_settings SET disabled_roles = CASE "
        " WHEN $2 = ANY(disabled_roles) THEN array_remove(disabled_roles, $2) "
        " ELSE array_append(disabled_roles, $2) END "
        "WHERE chat_id = $1 RETURNING disabled_roles",
        chat_id, role,
    )
    return role not in disabled


async def set_players(pool: asyncpg.Pool, chat_id: int, name: str, value: int) -> int:
    """Межі гравців; мінімум ніколи не більший за максимум."""
    lo, hi, _ = PLAYER_LIMITS[name]
    value = max(lo, min(hi, value))
    if name == "min_players":
        sql = "UPDATE group_settings SET min_players = LEAST($2, max_players) WHERE chat_id = $1 RETURNING min_players"
    else:
        sql = "UPDATE group_settings SET max_players = GREATEST($2, min_players) WHERE chat_id = $1 RETURNING max_players"
    return await pool.fetchval(sql, chat_id, value)


async def set_ratio(pool: asyncpg.Pool, chat_id: int, ratio: str) -> None:
    if ratio not in MAFIA_RATIOS:
        raise ValueError(ratio)
    await pool.execute("UPDATE group_settings SET mafia_ratio = $2 WHERE chat_id = $1", chat_id, ratio)


async def toggle_item(pool: asyncpg.Pool, chat_id: int, item: str) -> None:
    await pool.execute(
        "UPDATE group_settings SET disabled_items = CASE "
        " WHEN $2 = ANY(disabled_items) THEN array_remove(disabled_items, $2) "
        " ELSE array_append(disabled_items, $2) END WHERE chat_id = $1",
        chat_id, item,
    )


async def remember_admin(pool: asyncpg.Pool, user_id: int, chat_id: int) -> None:
    await pool.execute(
        "INSERT INTO chat_admins (user_id, chat_id) VALUES ($1, $2) "
        "ON CONFLICT (user_id, chat_id) DO UPDATE SET seen_at = now()", user_id, chat_id)


async def admin_chats(pool: asyncpg.Pool, user_id: int, limit: int = 10) -> list[tuple[int, str]]:
    rows = await pool.fetch(
        "SELECT a.chat_id, COALESCE(NULLIF(g.title, ''), a.chat_id::text) AS title FROM chat_admins a "
        "LEFT JOIN group_settings g ON g.chat_id = a.chat_id WHERE a.user_id = $1 "
        "ORDER BY a.seen_at DESC LIMIT $2", user_id, limit)
    return [(r["chat_id"], r["title"]) for r in rows]


async def reset(pool: asyncpg.Pool, chat_id: int) -> None:
    """Повертає налаштування чату до звичних (назва чату зберігається)."""
    async with pool.acquire() as conn, conn.transaction():
        title = await conn.fetchval("DELETE FROM group_settings WHERE chat_id = $1 RETURNING title", chat_id)
        await conn.execute("INSERT INTO group_settings (chat_id, title) VALUES ($1, $2)", chat_id, title or "")
