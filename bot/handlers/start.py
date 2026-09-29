"""Привітання, головне меню з розділами і правила.

Розділи відкриваються в тому самому повідомленні (edit), кнопка «Назад» повертає меню.
"""

from __future__ import annotations

import asyncpg
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot import economy, keyboards, texts
from bot.db import shop, users
from bot.db.users import User
from bot.engine.items import ITEMS
from bot.game.manager import GameManager
from bot.keyboards import MenuCb, SecCb

router = Router(name="start")


async def _edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    """Редагує повідомлення меню; якщо це повідомлення з медіа — редагує підпис."""
    await cb.answer()
    try:
        if cb.message.photo or cb.message.animation or cb.message.video:
            await cb.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await cb.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest:
        # Підпис до медіа обмежений 1024 символами — тоді надсилаємо розділ окремим повідомленням.
        await cb.message.answer(text, reply_markup=markup)


@router.message(CommandStart())
async def cmd_start(message: Message, manager: GameManager) -> None:
    private = message.chat.type == "private"
    markup = keyboards.main_menu(manager.bot_username) if private else None
    await manager.m.send_scene(message.chat.id, "start", texts.start(message.from_user.first_name), markup)


@router.message(Command("rules", "help"))
async def cmd_rules(message: Message) -> None:
    await message.answer(texts.rules())


@router.callback_query(MenuCb.filter())
async def on_menu(cb: CallbackQuery, manager: GameManager) -> None:
    await _edit(cb, texts.start(cb.from_user.first_name), keyboards.main_menu(manager.bot_username))


@router.callback_query(SecCb.filter())
async def on_section(cb: CallbackQuery, callback_data: SecCb, pool: asyncpg.Pool, user: User) -> None:
    from bot.handlers.profile import fmt_date, fmt_left

    match callback_data.name:
        case "howto":
            text = texts.SECTION_HOWTO
        case "game":
            text = texts.SECTION_GAME
        case "roles":
            text = texts.section_roles()
        case "items":
            text = texts.section_items()
        case "vip":
            text = texts.SECTION_VIP
        case "profile":
            inv = await shop.inventory(pool, user.id)
            inventory = [f"{texts.item_title(k)} ×{v}" for k, v in inv.items() if k in ITEMS]
            card = texts.profile(user.name, user.shagy, user.chervintsi,
                                 fmt_date(user.vip_until) if user.is_vip else None,
                                 user.games, user.wins, inventory)
            text = texts.section_profile(card)
        case "daily":
            amount = economy.DAILY_VIP if user.is_vip else economy.DAILY
            ok, next_at = await users.claim_daily(pool, user.id, amount, economy.DAILY_COOLDOWN)
            result = (texts.DAILY_OK.format(amount=amount, shagy=texts.SHAGY) if ok
                      else texts.DAILY_WAIT.format(left=fmt_left(next_at)))
            text = texts.section_daily(result)
        case _:
            await cb.answer()
            return
    await _edit(cb, text, keyboards.back_to_menu())
