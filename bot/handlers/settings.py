"""Налаштування гри для чату. Панель живе в особистих адміна: /settings у групі надсилає її туди."""

from __future__ import annotations

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from bot import keyboards, texts
from bot.config import Settings
from bot.db import groups
from bot.db import roles as roles_db
from bot.db.groups import MAFIA_RATIOS, PLAYER_LIMITS, TIMER_LIMITS, TOGGLES, GroupSettings
from bot.db.users import User
from bot.engine.items import ITEMS
from bot.engine.roles import ROLES
from bot.game.manager import GameManager
from bot.handlers.common import is_chat_admin, is_group
from bot.keyboards import SetCb

router = Router(name="settings")

# Модуль панелі → перемикачі, які в ньому показуються.
MODULE_TOGGLES = {
    "vote": ("secret_vote", "hide_dead_roles"),
    "omerta": ("omerta_dead", "omerta_night"),
    "lobby": ("pin_lobby", "start_admins_only"),
    "items": ("items_enabled",),
}
TOGGLE_MODULE = {key: module for module, keys in MODULE_TOGGLES.items() for key in keys}


def panel(s: GroupSettings, module: str, custom: list[dict] | None = None):
    """(текст, клавіатура) для модуля панелі."""
    if module == "timers" or module == "timer":
        return texts.SETTINGS_TIMERS_HEAD, keyboards.settings_timers(s)
    if module == "lobby":
        return texts.SETTINGS_LOBBY_HEAD, keyboards.settings_lobby(s)
    if module == "family":
        return texts.SETTINGS_FAMILY_HEAD, keyboards.settings_family(s)
    if module == "roles":
        return texts.SETTINGS_ROLES_HEAD, keyboards.settings_roles(s, custom or [])
    if module == "items":
        return texts.SETTINGS_ITEMS_HEAD, keyboards.settings_items(s)
    if module == "vote":
        return texts.SETTINGS_VOTE_HEAD, keyboards.settings_toggles(s, MODULE_TOGGLES["vote"])
    if module == "omerta":
        return texts.SETTINGS_OMERTA_HEAD, keyboards.settings_toggles(s, MODULE_TOGGLES["omerta"], "custom")
    if module == "custom":
        return texts.SETTINGS_CUSTOM_HEAD, keyboards.settings_custom(s.chat_id)
    if module == "reset":
        return texts.SETTINGS_RESET_HEAD, keyboards.settings_reset(s.chat_id)
    return texts.settings_home(s.title, s), keyboards.settings_home(s.chat_id)


async def send_home(bot: Bot, user_id: int, pool: asyncpg.Pool, chat_id: int) -> None:
    s = await groups.get(pool, chat_id)
    text, markup = panel(s, "home")
    await bot.send_message(user_id, text, reply_markup=markup)


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot, pool: asyncpg.Pool, config: Settings, user: User,
                       manager: GameManager) -> None:
    if not is_group(message):
        chats = await groups.admin_chats(pool, user.id)
        if not chats:
            await message.answer(texts.SETTINGS_NO_CHATS)
        else:
            await message.answer(texts.SETTINGS_PICK_CHAT, reply_markup=keyboards.settings_chats(chats))
        return
    chat_id = message.chat.id
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    await groups.get(pool, chat_id, message.chat.title or "")
    await groups.remember_admin(pool, user.id, chat_id)
    link = f"https://t.me/{manager.bot_username}"
    try:
        await send_home(bot, user.id, pool, chat_id)
    except (TelegramForbiddenError, TelegramBadRequest):
        # Адмін ще не запускав бота - в особисті писати не можна.
        await message.answer(texts.SETTINGS_OPEN_PM, reply_markup=keyboards.settings_open_pm(
            f"{link}?start=settings{chat_id}", texts.SETTINGS_OPEN_PM_BTN))
        return
    await message.answer(texts.SETTINGS_SENT, reply_markup=keyboards.settings_open_pm(link, texts.SETTINGS_SENT_BTN))


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^settings-?\d+$")), F.chat.type == "private")
async def settings_link(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool,
                        config: Settings, user: User) -> None:
    chat_id = int(command.args[len("settings"):])
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    await groups.remember_admin(pool, user.id, chat_id)
    await send_home(bot, user.id, pool, chat_id)


@router.callback_query(SetCb.filter())
async def on_settings(cb: CallbackQuery, callback_data: SetCb, bot: Bot, pool: asyncpg.Pool,
                      config: Settings, user: User) -> None:
    # Старі панелі (до переїзду в особисті) не мали chat - тоді це сам чат повідомлення.
    chat_id = callback_data.chat or cb.message.chat.id
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await cb.answer(texts.ADMIN_ONLY, show_alert=True)
        return
    action, key, delta = callback_data.action, callback_data.key, callback_data.delta
    if action == "noop":
        await cb.answer()
        return

    s = await groups.get(pool, chat_id)
    module, note = action, None
    if action == "timer" and key in TIMER_LIMITS:
        await groups.set_timer(pool, chat_id, key, getattr(s, key) + delta)
        module = "lobby" if key == "reg_time" else "timers"
    elif action == "players" and key in PLAYER_LIMITS:
        await groups.set_players(pool, chat_id, key, getattr(s, key) + delta)
        module = "family"
    elif action == "ratio" and key in MAFIA_RATIOS:
        await groups.set_ratio(pool, chat_id, key)
        module = "family"
    elif action == "toggle" and key in TOGGLES:
        await groups.toggle(pool, chat_id, key)
        module = TOGGLE_MODULE.get(key, "home")
    elif action == "role" and key in ROLES and ROLES[key].optional and not ROLES[key].custom:
        await groups.toggle_role(pool, chat_id, key)
        module = "roles"
    elif action == "crole" and key.isdigit():
        role = await roles_db.get(pool, int(key))
        if role and role["chat_id"] == chat_id:
            await roles_db.toggle(pool, role["id"])
        module = "roles"
    elif action == "item" and key in ITEMS:
        await groups.toggle_item(pool, chat_id, key)
        module = "items"
    elif action == "reset_ok":
        await groups.reset(pool, chat_id)
        module, note = "home", texts.SETTINGS_RESET_DONE
    elif action == "refresh":
        module, note = "home", "🔄"

    s = await groups.get(pool, chat_id)
    custom = await roles_db.list_for_chat(pool, chat_id) if module == "roles" else None
    text, markup = panel(s, module, custom)
    await cb.answer(note)
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass  # нічого не змінилось (межа значення або меню вже актуальне)
