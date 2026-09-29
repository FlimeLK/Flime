"""Ярмарок предметів."""

from __future__ import annotations

import asyncpg
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot import texts
from bot.db import shop, users
from bot.db.users import User
from bot.engine import items as it
from bot.ui.buttons import PRIMARY, btn, rows

router = Router(name="shop")


class BuyCb(CallbackData, prefix="buy"):
    item: str


def shop_keyboard() -> InlineKeyboardMarkup:
    buttons = [btn(f"{item.name} · {item.price}", BuyCb(item=item.key), emo=item.key, style=PRIMARY)
               for item in it.ITEMS.values()]
    return InlineKeyboardMarkup(inline_keyboard=rows(buttons, 2))


async def shop_text(pool: asyncpg.Pool, user: User, balance: int | None = None) -> str:
    inv = await shop.inventory(pool, user.id)
    slots = it.VIP_POCKET_SLOTS if user.is_vip else it.BASE_POCKET_SLOTS
    return texts.shop(user.shagy if balance is None else balance, inv, slots)


@router.message(Command("shop"))
async def cmd_shop(message: Message, pool: asyncpg.Pool, user: User) -> None:
    if message.chat.type != "private":
        await message.answer(texts.PRIVATE_ONLY)
        return
    await message.answer(await shop_text(pool, user), reply_markup=shop_keyboard())


@router.callback_query(BuyCb.filter())
async def on_buy(cb: CallbackQuery, callback_data: BuyCb, pool: asyncpg.Pool, user: User) -> None:
    item = it.ITEMS.get(callback_data.item)
    if item is None:
        await cb.answer()
        return
    balance = await shop.buy(pool, user.id, item.key, item.price)
    if balance is None:
        await cb.answer(texts.SHOP_NO_MONEY, show_alert=True)
        return
    await cb.answer(texts.SHOP_BOUGHT.format(item=texts.item_title(item.key), balance=balance, shagy=texts.SHAGY))
    fresh = await users.get(pool, user.id)
    try:
        await cb.message.edit_text(await shop_text(pool, fresh), reply_markup=shop_keyboard())
    except TelegramBadRequest:
        pass
