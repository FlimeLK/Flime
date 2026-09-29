"""VIP, червінці та оплата зірками Telegram (XTR)."""

from __future__ import annotations

import logging

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery

from bot import economy, texts
from bot.db import payments, users
from bot.db.users import User
from bot.handlers.profile import fmt_date
from bot.ui import media
from bot.ui.buttons import PRIMARY, SUCCESS, btn

router = Router(name="payments")
log = logging.getLogger(__name__)

EXCHANGE_AMOUNTS = (1, 5, 20)


class StarsCb(CallbackData, prefix="stars"):
    product: str


class VipChervCb(CallbackData, prefix="vipch"):
    pass


class ExchangeCb(CallbackData, prefix="exch"):
    amount: int


def vip_keyboard() -> InlineKeyboardMarkup:
    vip = economy.PRODUCTS["vip_30"]
    keyboard = [
        [btn(f"{vip.title} - {vip.stars} ⭐", StarsCb(product=vip.key), emo="vip", style=SUCCESS)],
        [btn(f"VIP за {economy.VIP_PRICE_CHERV} червінців", VipChervCb(), emo="vip", style=PRIMARY)],
        [btn(f"{p.chervintsi} - {p.stars} ⭐", StarsCb(product=p.key), emo="cherv")
         for p in economy.PRODUCTS.values() if p.chervintsi],
        [btn(f"{a} → {a * economy.EXCHANGE_RATE}", ExchangeCb(amount=a), emo="refresh") for a in EXCHANGE_AMOUNTS],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def vip_text(user: User) -> str:
    return texts.vip_menu(user.chervintsi, fmt_date(user.vip_until) if user.is_vip else None,
                          economy.VIP_PRICE_CHERV, economy.EXCHANGE_RATE)


async def refresh(cb: CallbackQuery, pool: asyncpg.Pool, user_id: int) -> None:
    fresh = await users.get(pool, user_id)
    try:
        await cb.message.edit_text(vip_text(fresh), reply_markup=vip_keyboard())
    except TelegramBadRequest:
        pass


@router.message(Command("vip"))
async def cmd_vip(message: Message, user: User) -> None:
    if message.chat.type != "private":
        await message.answer(texts.PRIVATE_ONLY)
        return
    await message.answer(vip_text(user), reply_markup=vip_keyboard())


@router.callback_query(StarsCb.filter())
async def on_stars(cb: CallbackQuery, callback_data: StarsCb, bot: Bot) -> None:
    product = economy.PRODUCTS.get(callback_data.product)
    if product is None:
        await cb.answer(texts.PAYMENT_UNKNOWN, show_alert=True)
        return
    await cb.answer()
    await bot.send_invoice(
        chat_id=cb.from_user.id,
        title=product.title,
        description=f"{texts.GAME_NAME}: {product.title}",
        payload=product.key,
        currency="XTR",
        prices=[LabeledPrice(label=product.title, amount=product.stars)],
    )


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    product = economy.PRODUCTS.get(query.invoice_payload)
    if product is None or query.currency != "XTR" or query.total_amount != product.stars:
        await query.answer(ok=False, error_message=texts.PAYMENT_UNKNOWN)
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(message: Message, pool: asyncpg.Pool, user: User) -> None:
    sp = message.successful_payment
    product = economy.PRODUCTS.get(sp.invoice_payload)
    if product is None:
        log.error("Paid unknown product %s by %s (charge %s)", sp.invoice_payload, user.id,
                  sp.telegram_payment_charge_id)
        await message.answer(texts.PAYMENT_UNKNOWN)
        return
    async with pool.acquire() as conn, conn.transaction():
        if not await payments.record(conn, user.id, product.key, sp.total_amount, sp.telegram_payment_charge_id):
            return  # уже оброблено
        if product.chervintsi:
            await users.add_balance(conn, user.id, "chervintsi", product.chervintsi)
        until = await users.extend_vip(conn, user.id, product.vip_days) if product.vip_days else None
    if until:
        await message.answer(texts.VIP_BOUGHT.format(until=fmt_date(until)), message_effect_id=media.EFFECT_PARTY)
    else:
        await message.answer(texts.CHERV_BOUGHT.format(amount=product.chervintsi),
                             message_effect_id=media.EFFECT_FIRE)


@router.callback_query(VipChervCb.filter())
async def on_vip_cherv(cb: CallbackQuery, pool: asyncpg.Pool, user: User) -> None:
    async with pool.acquire() as conn, conn.transaction():
        left = await users.add_balance(conn, user.id, "chervintsi", -economy.VIP_PRICE_CHERV)
        until = await users.extend_vip(conn, user.id, economy.VIP_DAYS) if left is not None else None
    if until is None:
        await cb.answer(texts.VIP_NO_CHERV, show_alert=True)
        return
    await cb.answer(texts.VIP_BOUGHT.format(until=fmt_date(until)), show_alert=True)
    await refresh(cb, pool, user.id)


@router.callback_query(ExchangeCb.filter())
async def on_exchange(cb: CallbackQuery, callback_data: ExchangeCb, pool: asyncpg.Pool, user: User) -> None:
    amount = callback_data.amount
    if amount not in EXCHANGE_AMOUNTS:
        await cb.answer()
        return
    shagy = amount * economy.EXCHANGE_RATE
    async with pool.acquire() as conn, conn.transaction():
        left = await users.add_balance(conn, user.id, "chervintsi", -amount)
        if left is not None:
            await users.add_balance(conn, user.id, "shagy", shagy)
    if left is None:
        await cb.answer(texts.VIP_NO_CHERV, show_alert=True)
        return
    await cb.answer(texts.EXCHANGED.format(cherv=amount, cherv_icon=texts.CHERV, shagy=shagy,
                                           shagy_icon=texts.SHAGY))
    await refresh(cb, pool, user.id)
