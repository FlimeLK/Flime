"""Головне меню, привітання і правила."""

from __future__ import annotations

import asyncpg
from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.db import users
from bot.db.users import User
from bot.handlers.common import MenuCb, back_button
from bot.handlers.payments import vip_keyboard, vip_text
from bot.handlers.profile import claim_daily, profile_keyboard, profile_text
from bot.handlers.shop import shop_keyboard, shop_text

router = Router(name="start")


async def menu_keyboard(bot: Bot) -> InlineKeyboardMarkup:
    me = await bot.me()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=texts.ADD_TO_GROUP, url=f"https://t.me/{me.username}?startgroup=true"))
    for action, label in texts.MENU_BUTTONS.items():
        kb.button(text=label, callback_data=MenuCb(action=action))
    kb.adjust(1, 2, 2, 1)
    return kb.as_markup()


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button()]])


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot) -> None:
    if command.args == "rules":
        await message.answer(texts.rules(), reply_markup=rules_keyboard())
        return
    markup = await menu_keyboard(bot) if message.chat.type == "private" else None
    await message.answer(texts.START, reply_markup=markup)


@router.message(Command("rules", "help"))
async def cmd_rules(message: Message) -> None:
    markup = rules_keyboard() if message.chat.type == "private" else None
    await message.answer(texts.rules(), reply_markup=markup)


@router.callback_query(MenuCb.filter())
async def on_menu(cb: CallbackQuery, callback_data: MenuCb, bot: Bot, pool: asyncpg.Pool, user: User) -> None:
    action = callback_data.action
    if action == "daily":
        await cb.answer(await claim_daily(pool, user), show_alert=True)
        return
    await cb.answer()
    if action == "profile":
        text, markup = await profile_text(pool, user), profile_keyboard()
    elif action == "shop":
        text, markup = await shop_text(pool, user), shop_keyboard()
    elif action == "vip":
        text, markup = vip_text(await users.get(pool, user.id)), vip_keyboard()
    elif action == "rules":
        text, markup = texts.rules(), rules_keyboard()
    else:
        text, markup = texts.START, await menu_keyboard(bot)
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass
