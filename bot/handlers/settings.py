"""Налаштування гри для чату (лише адміністратори)."""

from __future__ import annotations

import asyncpg
from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot import keyboards, texts
from bot.config import Settings
from bot.db import groups
from bot.db import roles as roles_db
from bot.db.groups import TIMER_LIMITS, TOGGLES
from bot.db.users import User
from bot.engine.roles import ROLES
from bot.game.manager import GameManager
from bot.handlers.common import is_chat_admin, is_group
from bot.keyboards import SetCb

router = Router(name="settings")

VOTE_TOGGLES = ("secret_vote", "hide_dead_roles")
ITEM_TOGGLES = ("items_enabled",)


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot, pool: asyncpg.Pool, config: Settings, user: User) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    if not await is_chat_admin(bot, message.chat.id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    await groups.get(pool, message.chat.id, message.chat.title or "")
    await message.answer(texts.settings_home(message.chat.title or ""), reply_markup=keyboards.settings_home())


@router.callback_query(SetCb.filter())
async def on_settings(cb: CallbackQuery, callback_data: SetCb, bot: Bot, pool: asyncpg.Pool,
                      config: Settings, user: User, manager: GameManager) -> None:
    chat_id = cb.message.chat.id
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await cb.answer(texts.ADMIN_ONLY, show_alert=True)
        return
    action, key = callback_data.action, callback_data.key
    if action == "noop":
        await cb.answer()
        return

    s = await groups.get(pool, chat_id, cb.message.chat.title or "")
    if action == "timer" and key in TIMER_LIMITS:
        await groups.set_timer(pool, chat_id, key, getattr(s, key) + callback_data.delta)
    elif action == "toggle" and key in TOGGLES:
        await groups.toggle(pool, chat_id, key)
    elif action == "role" and key in ROLES and ROLES[key].optional and not ROLES[key].custom:
        await groups.toggle_role(pool, chat_id, key)
    elif action == "crole" and key.isdigit():
        role = await roles_db.get(pool, int(key))
        if role and role["chat_id"] == chat_id:
            await roles_db.toggle(pool, role["id"])
    s = await groups.get(pool, chat_id)

    if action in ("timers", "timer"):
        text, markup = texts.SETTINGS_TIMERS_HEAD, keyboards.settings_timers(s)
    elif action in ("roles", "role", "crole"):
        custom = await roles_db.list_for_chat(pool, chat_id)
        text = texts.SETTINGS_ROLES_HEAD
        markup = keyboards.settings_roles(s, custom, manager.bot_username, chat_id)
    elif action == "vote" or (action == "toggle" and key in VOTE_TOGGLES):
        text, markup = texts.SETTINGS_VOTE_HEAD, keyboards.settings_toggles(s, VOTE_TOGGLES)
    elif action == "items" or (action == "toggle" and key in ITEM_TOGGLES):
        text, markup = texts.SETTINGS_ITEMS_HEAD, keyboards.settings_toggles(s, ITEM_TOGGLES)
    else:  # home | refresh
        text, markup = texts.settings_home(cb.message.chat.title or ""), keyboards.settings_home()
    await cb.answer("🔄" if action == "refresh" else None)
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass  # нічого не змінилось (межа таймера або меню вже актуальне)
