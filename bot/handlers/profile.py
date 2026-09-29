"""Профіль, щоденний конверт, топ і промокоди."""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot import economy, texts
from bot.db import games, promocodes, shop, users
from bot.db.users import User
from bot.engine.items import ITEMS
from bot.handlers.common import is_group

router = Router(name="profile")


def fmt_date(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%d.%m.%Y")


def fmt_left(until: datetime) -> str:
    seconds = max(0, int((until - datetime.now(UTC)).total_seconds()))
    hours, rem = divmod(seconds, 3600)
    return f"{hours} год {rem // 60} хв"


@router.message(Command("profile", "me"))
async def cmd_profile(message: Message, pool: asyncpg.Pool, user: User) -> None:
    inv = await shop.inventory(pool, user.id)
    inventory = [f"{texts.item_title(k)} ×{v}" for k, v in inv.items() if k in ITEMS]
    await message.answer(texts.profile(
        user.name, user.shagy, user.chervintsi,
        fmt_date(user.vip_until) if user.is_vip else None,
        user.games, user.wins, inventory,
    ))


@router.message(Command("daily"))
async def cmd_daily(message: Message, pool: asyncpg.Pool, user: User) -> None:
    amount = economy.DAILY_VIP if user.is_vip else economy.DAILY
    ok, next_at = await users.claim_daily(pool, user.id, amount, economy.DAILY_COOLDOWN)
    if ok:
        await message.answer(texts.DAILY_OK.format(amount=amount, shagy=texts.SHAGY))
    else:
        await message.answer(texts.DAILY_WAIT.format(left=fmt_left(next_at)))


@router.message(Command("top"))
async def cmd_top(message: Message, pool: asyncpg.Pool) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    rows = await games.top_for_chat(pool, message.chat.id)
    if not rows:
        await message.answer(texts.TOP_EMPTY)
        return
    lines = [texts.TOP_HEAD]
    for i, r in enumerate(rows):
        mark = texts.TOP_MEDALS[i] if i < 3 else f"<b>{i + 1}.</b>"
        lines.append(f"{mark} {texts.escape(r['name'])} - :trophy: {r['wins']} · :dice: {r['games']}")
    await message.answer("\n".join(lines))


@router.message(Command("promo"))
async def cmd_promo(message: Message, command: CommandObject, pool: asyncpg.Pool, user: User) -> None:
    code = (command.args or "").strip()
    if not code:
        await message.answer(texts.PROMO_USAGE)
        return
    result = await promocodes.activate(pool, code, user.id)
    if isinstance(result, str):
        await message.answer(texts.PROMO_ERRORS[result])
        return
    await message.answer(texts.promo_ok(result.shagy, result.chervintsi, result.vip_days))
