"""Налаштування гри для чату (лише адміністратори). Панель відкривається в особистих з ботом."""

from __future__ import annotations

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.config import Settings
from bot.db import groups
from bot.db.groups import TIMER_LIMITS, TOGGLES, GroupSettings
from bot.db.users import User
from bot.engine.roles import ROLES
from bot.handlers.common import SetCb, is_chat_admin, is_group, send_admin_panel
from bot.handlers.roles_builder import RoleCb

router = Router(name="settings")

__all__ = ["SetCb", "router"]


def main_keyboard(s: GroupSettings) -> InlineKeyboardMarkup:
    chat = s.chat_id
    kb = InlineKeyboardBuilder()
    for key, label in texts.TIMER_NAMES.items():
        step = TIMER_LIMITS[key][2]
        kb.button(text="➖", callback_data=SetCb(action="timer", chat=chat, key=key, delta=-step))
        kb.button(text=f"{label}: {texts.fmt_seconds(getattr(s, key))}", callback_data=SetCb(action="noop", chat=chat))
        kb.button(text="➕", callback_data=SetCb(action="timer", chat=chat, key=key, delta=step))
    for key in TOGGLES:
        kb.button(text=texts.TOGGLE_LABELS[key][int(getattr(s, key))],
                  callback_data=SetCb(action="toggle", chat=chat, key=key))
    kb.button(text=texts.RB_OPEN_BUTTON, callback_data=RoleCb(action="list", chat=chat))
    kb.button(text=texts.SETTINGS_ROLES_BUTTON, callback_data=SetCb(action="roles", chat=chat))
    kb.button(text=texts.SETTINGS_CLOSE, callback_data=SetCb(action="close", chat=chat))
    kb.adjust(*([3] * len(texts.TIMER_NAMES)), *([1] * len(TOGGLES)), 1, 1, 1)
    return kb.as_markup()


def roles_keyboard(s: GroupSettings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in ROLES.values():
        if not r.optional:
            continue
        mark = "❌" if r.key in s.disabled_roles else "✅"
        kb.button(text=f"{mark} {r.title} ({r.min_players}+)",
                  callback_data=SetCb(action="role", chat=s.chat_id, key=r.key))
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=texts.SETTINGS_BACK, callback_data=SetCb(action="menu", chat=s.chat_id).pack()))
    return kb.as_markup()


async def panel(pool: asyncpg.Pool, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    s = await groups.get(pool, chat_id)
    title = await pool.fetchval("SELECT title FROM group_settings WHERE chat_id = $1", chat_id) or str(chat_id)
    return texts.settings_head(title), main_keyboard(s)


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot, pool: asyncpg.Pool, config: Settings, user: User) -> None:
    if not is_group(message):
        await message.answer(texts.SETTINGS_IN_GROUP)
        return
    if not await is_chat_admin(bot, message.chat.id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    await groups.get(pool, message.chat.id, message.chat.title or "")
    await send_admin_panel(message, bot, f"settings{message.chat.id}", *await panel(pool, message.chat.id))


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^settings-?\d+$")), F.chat.type == "private")
async def open_via_link(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool,
                        config: Settings, user: User) -> None:
    chat_id = int(command.args[8:])
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await message.answer(texts.RB_NO_RIGHTS)
        return
    text, markup = await panel(pool, chat_id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(SetCb.filter())
async def on_settings(cb: CallbackQuery, callback_data: SetCb, bot: Bot, pool: asyncpg.Pool,
                      config: Settings, user: User) -> None:
    chat_id = callback_data.chat
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await cb.answer(texts.ADMIN_ONLY, show_alert=True)
        return
    action, key = callback_data.action, callback_data.key
    if action == "noop":
        await cb.answer()
        return
    if action == "close":
        await cb.answer()
        await cb.message.edit_text(texts.SETTINGS_CLOSED)
        return

    s = await groups.get(pool, chat_id)
    if action == "timer" and key in TIMER_LIMITS:
        await groups.set_timer(pool, chat_id, key, getattr(s, key) + callback_data.delta)
    elif action == "toggle" and key in TOGGLES:
        await groups.toggle(pool, chat_id, key)
    elif action == "role" and key in ROLES and ROLES[key].optional:
        await groups.toggle_role(pool, chat_id, key)
    if action in ("roles", "role"):
        text, markup = texts.SETTINGS_ROLES_HEAD, roles_keyboard(await groups.get(pool, chat_id))
    else:
        text, markup = await panel(pool, chat_id)
    await cb.answer()
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass  # нічого не змінилось (межа таймера)
