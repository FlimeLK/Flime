"""Налаштування гри для кожного чату."""

from __future__ import annotations

from dataclasses import dataclass, field

import asyncpg

# Поле → (мінімум, максимум, крок) у секундах.
TIMER_LIMITS: dict[str, tuple[int, int, int]] = {
    "reg_time": (30, 300, 15),
    "night_time": (30, 180, 15),
    "day_time": (15, 300, 15),
    "vote_time": (20, 120, 5),
    "confirm_time": (15, 90, 5),
}
TOGGLES = ("hide_dead_roles", "secret_vote", "items_enabled")


@dataclass
class GroupSettings:
    chat_id: int
    reg_time: int = 90
    night_time: int = 60
    day_time: int = 60
    vote_time: int = 45
    confirm_time: int = 30
    disabled_roles: list[str] = field(default_factory=list)
    hide_dead_roles: bool = False
    secret_vote: bool = False
    items_enabled: bool = True

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
    return GroupSettings.from_dict({**dict(r), "disabled_roles": list(r["disabled_roles"])})


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
