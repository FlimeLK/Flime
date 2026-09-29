"""Привітання, головне меню і правила."""

from __future__ import annotations

import asyncpg
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot import texts
from bot.db.users import User
from bot.game.manager import GameManager
from bot.ui.buttons import PRIMARY, SUCCESS, btn

router = Router(name="start")


class MenuCb(CallbackData, prefix="menu"):
    action: str


def menu_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("Додати бота в групу", url=f"https://t.me/{bot_username}?startgroup=true", emo="people", style=SUCCESS)],
        [btn("Профіль", MenuCb(action="profile"), emo="profile"),
         btn("Ярмарок", MenuCb(action="shop"), emo="shop")],
        [btn("Гостинець", MenuCb(action="daily"), emo="gift"),
         btn("VIP", MenuCb(action="vip"), emo="vip", style=PRIMARY)],
        [btn("Правила та ролі", MenuCb(action="rules"), emo="rules")],
    ])


@router.message(CommandStart())
async def cmd_start(message: Message, manager: GameManager) -> None:
    markup = menu_keyboard(manager.bot_username) if message.chat.type == "private" else None
    await manager.m.send_scene(message.chat.id, "start", texts.START, markup)


@router.message(Command("rules", "help"))
async def cmd_rules(message: Message) -> None:
    await message.answer(texts.rules())


@router.callback_query(MenuCb.filter())
async def on_menu(cb: CallbackQuery, callback_data: MenuCb, pool: asyncpg.Pool, user: User) -> None:
    from bot.handlers import payments, profile, shop

    await cb.answer()
    msg = cb.message
    match callback_data.action:
        case "profile":
            await profile.cmd_profile(msg, pool, user)
        case "shop":
            await shop.cmd_shop(msg, pool, user)
        case "daily":
            await profile.cmd_daily(msg, pool, user)
        case "vip":
            await payments.cmd_vip(msg, user)
        case "rules":
            await cmd_rules(msg)
