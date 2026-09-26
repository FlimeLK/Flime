"""Ярмарок предметів."""

from __future__ import annotations

import asyncpg
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.db import shop, users
from bot.db.users import User
from bot.engine import items as it
from bot.handlers.common import back_button

router = Router(name="shop")


class BuyCb(CallbackData, prefix="buy"):
    item: str


def shop_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item in it.ITEMS.values():
        kb.button(text=f"{item.title} · {item.price} {texts.SHAGY}", callback_data=BuyCb(item=item.key))
    kb.adjust(2)
    kb.row(back_button())
    return kb.as_markup()


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
    await cb.answer(texts.SHOP_BOUGHT.format(item=item.title, balance=texts.shagy(balance)))
    fresh = await users.get(pool, user.id)
    try:
        await cb.message.edit_text(await shop_text(pool, fresh), reply_markup=shop_keyboard())
    except TelegramBadRequest:
        pass
