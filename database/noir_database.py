"""
Дані бота «Кримінальне чтиво» (NOIR) у PostgreSQL — той самий підхід, що й у Мафії.
"""

from __future__ import annotations

import random
from typing import Any

from database.database import conn, cursor, ensure_db_connection_usable, run_db_call_async

_NOIR_SELECT = """
    SELECT user_id, dossier_no, cash, xp, vigilance_lvl, persuasion_lvl,
           has_flashlight, batteries, camel_packs, whiskey_unused, case1_started
    FROM noir_users WHERE user_id = %s
"""

_NOIR_KEYS = (
    "user_id",
    "dossier_no",
    "cash",
    "xp",
    "vigilance_lvl",
    "persuasion_lvl",
    "has_flashlight",
    "batteries",
    "camel_packs",
    "whiskey_unused",
    "case1_started",
)

_NOIR_MUTABLE_FIELDS = frozenset(_NOIR_KEYS) - {"user_id"}
_NOIR_BUY_FIELDS = frozenset({"has_flashlight", "batteries", "camel_packs", "whiskey_unused"})


def _row_to_dict(row: tuple | None) -> dict[str, Any]:
    if row is None:
        return {}
    return dict(zip(_NOIR_KEYS, row))


def _noir_get_or_create_sync(user_id: int) -> dict[str, Any]:
    ensure_db_connection_usable()
    cursor.execute(_NOIR_SELECT, (user_id,))
    row = cursor.fetchone()
    if row:
        return _row_to_dict(row)
    dossier = random.randint(1000, 9999)
    cursor.execute(
        """
        INSERT INTO noir_users (user_id, dossier_no) VALUES (%s, %s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id, dossier),
    )
    conn.commit()
    cursor.execute(_NOIR_SELECT, (user_id,))
    row = cursor.fetchone()
    return _row_to_dict(row)


def _noir_update_sync(user_id: int, **fields: int) -> None:
    if not fields:
        return
    bad = set(fields) - _NOIR_MUTABLE_FIELDS
    if bad:
        raise ValueError(f"Invalid noir user fields: {bad}")
    ensure_db_connection_usable()
    parts = [f"{k} = %s" for k in fields]
    vals = list(fields.values()) + [user_id]
    cursor.execute(
        f"UPDATE noir_users SET {', '.join(parts)} WHERE user_id = %s",
        vals,
    )
    conn.commit()


def _noir_try_buy_sync(
    user_id: int,
    *,
    price: int,
    field: str,
    delta: int = 1,
    max_field: int | None = None,
    already_has_check: str | None = None,
) -> tuple[bool, str]:
    if field not in _NOIR_BUY_FIELDS:
        return False, "Внутрішня помилка магазину."
    ensure_db_connection_usable()
    cursor.execute(_NOIR_SELECT, (user_id,))
    row = cursor.fetchone()
    if row is None:
        return False, "Спочатку натисніть /start."
    u = _row_to_dict(row)
    if already_has_check:
        if already_has_check not in _NOIR_KEYS:
            return False, "Внутрішня помилка магазину."
        if u.get(already_has_check, 0):
            return False, "У вас уже є цей предмет."
    if u["cash"] < price:
        return False, "Недостатньо коштів."
    new_cash = u["cash"] - price
    new_val = u[field] + delta
    if max_field is not None and new_val > max_field:
        new_val = max_field
    cursor.execute(
        f"UPDATE noir_users SET cash = %s, {field} = %s WHERE user_id = %s",
        (new_cash, new_val, user_id),
    )
    conn.commit()
    return True, ""


async def noir_get_or_create_user(user_id: int) -> dict[str, Any]:
    return await run_db_call_async(_noir_get_or_create_sync, user_id)


async def noir_update_user(user_id: int, **fields: int) -> None:
    await run_db_call_async(_noir_update_sync, user_id, **fields)


async def noir_try_buy(
    user_id: int,
    *,
    price: int,
    field: str,
    delta: int = 1,
    max_field: int | None = None,
    already_has_check: str | None = None,
) -> tuple[bool, str]:
    return await run_db_call_async(
        _noir_try_buy_sync,
        user_id,
        price=price,
        field=field,
        delta=delta,
        max_field=max_field,
        already_has_check=already_has_check,
    )
