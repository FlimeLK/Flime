"""Профіль, щоденний гостинець, топ і промокоди."""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, Message

from bot import economy, texts
from bot.db import games, promocodes, shop, users
from bot.db.users import User
from bot.engine.items import ITEMS
from bot.handlers.common import back_button, is_group

router = Router(name="profile")


def fmt_date(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%d.%m.%Y")


def fmt_left(until: datetime) -> str:
    seconds = max(0, int((until - datetime.now(UTC)).total_seconds()))
    hours, rem = divmod(seconds, 3600)
    return f"{hours} год {rem // 60} хв"


async def profile_text(pool: asyncpg.Pool, user: User) -> str:
    inv = await shop.inventory(pool, user.id)
    inventory = [f"{ITEMS[k].title} ×{v}" for k, v in inv.items() if k in ITEMS]
    return texts.profile(
        user.name, user.shagy, user.chervintsi,
        fmt_date(user.vip_until) if user.is_vip else None,
        user.games, user.wins, inventory,
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button()]])


async def claim_daily(pool: asyncpg.Pool, user: User) -> str:
    amount = economy.DAILY_VIP if user.is_vip else economy.DAILY
    ok, next_at = await users.claim_daily(pool, user.id, amount, economy.DAILY_COOLDOWN)
    if ok:
        return texts.DAILY_OK.format(amount=amount, shagy=texts.SHAGY)
    return texts.DAILY_WAIT.format(left=fmt_left(next_at))


@router.message(Command("profile", "me"))
async def cmd_profile(message: Message, pool: asyncpg.Pool, user: User) -> None:
    markup = profile_keyboard() if message.chat.type == "private" else None
    await message.answer(await profile_text(pool, user), reply_markup=markup)


@router.message(Command("daily"))
async def cmd_daily(message: Message, pool: asyncpg.Pool, user: User) -> None:
    await message.answer(await claim_daily(pool, user))


@router.message(Command("top"))
async def cmd_top(message: Message, pool: asyncpg.Pool) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    rows = await games.top_for_chat(pool, message.chat.id)
    if not rows:
        await message.answer(texts.TOP_EMPTY)
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(rows):
        mark = medals[i] if i < 3 else f"{i + 1}."
        title, _ = texts.rank(r["wins"])
        lines.append(f"{mark} <b>{texts.escape(r['name'])}</b> — 🏆 {r['wins']} · 🎲 {r['games']}  <i>{title}</i>")
    await message.answer(texts.TOP_HEAD + "\n" + texts.quote("\n".join(lines)))


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
