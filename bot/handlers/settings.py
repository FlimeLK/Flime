"""Налаштування гри для чату (лише адміністратори)."""

from __future__ import annotations

import asyncpg
from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot import texts
from bot.config import Settings
from bot.db import groups
from bot.db.groups import TIMER_LIMITS, TOGGLES, GroupSettings
from bot.db.users import User
from bot.engine.roles import ROLES
from bot.handlers.common import is_chat_admin, is_group
from bot.ui.buttons import DANGER, PRIMARY, SUCCESS, btn, rows

router = Router(name="settings")


class SetCb(CallbackData, prefix="set"):
    action: str   # menu | roles | timer | toggle | role | close | noop
    key: str = ""
    delta: int = 0


def main_keyboard(s: GroupSettings) -> InlineKeyboardMarkup:
    keyboard = []
    for key, (emo, label) in texts.TIMER_NAMES.items():
        step = TIMER_LIMITS[key][2]
        keyboard.append([
            btn("−", SetCb(action="timer", key=key, delta=-step)),
            btn(f"{label}: {texts.fmt_seconds(getattr(s, key))}", SetCb(action="noop"), emo=emo),
            btn("+", SetCb(action="timer", key=key, delta=step)),
        ])
    for key in TOGGLES:
        on = bool(getattr(s, key))
        emo, label = texts.TOGGLE_LABELS[key][int(on)]
        keyboard.append([btn(label, SetCb(action="toggle", key=key), emo=emo, style=SUCCESS if on else None)])
    keyboard.append([
        btn("Ролі", SetCb(action="roles"), emo="mask", style=PRIMARY),
        btn("Готово", SetCb(action="close"), emo="ok"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def roles_keyboard(s: GroupSettings) -> InlineKeyboardMarkup:
    buttons = []
    for r in ROLES.values():
        if not r.optional:
            continue
        on = r.key not in s.disabled_roles
        buttons.append(btn(f"{r.name} ({r.min_players}+)", SetCb(action="role", key=r.key), emo=r.key,
                           style=SUCCESS if on else DANGER))
    keyboard = rows(buttons, 2)
    keyboard.append([btn("Назад", SetCb(action="menu"), emo="back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot, pool: asyncpg.Pool, config: Settings, user: User) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    if not await is_chat_admin(bot, message.chat.id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    s = await groups.get(pool, message.chat.id, message.chat.title or "")
    await message.answer(texts.SETTINGS_HEAD, reply_markup=main_keyboard(s))


@router.callback_query(SetCb.filter())
async def on_settings(cb: CallbackQuery, callback_data: SetCb, bot: Bot, pool: asyncpg.Pool,
                      config: Settings, user: User) -> None:
    chat_id = cb.message.chat.id
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
    text, markup = texts.SETTINGS_HEAD, None
    if action == "timer" and key in TIMER_LIMITS:
        await groups.set_timer(pool, chat_id, key, getattr(s, key) + callback_data.delta)
    elif action == "toggle" and key in TOGGLES:
        await groups.toggle(pool, chat_id, key)
    elif action == "role" and key in ROLES and ROLES[key].optional:
        await groups.toggle_role(pool, chat_id, key)
    s = await groups.get(pool, chat_id)
    if action in ("roles", "role"):
        text, markup = texts.SETTINGS_ROLES_HEAD, roles_keyboard(s)
    else:
        markup = main_keyboard(s)
    await cb.answer()
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass  # нічого не змінилось (межа таймера)
