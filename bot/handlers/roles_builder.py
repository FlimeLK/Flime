"""Конструктор своїх ролей чату. Працює в особистих з ботом, лише для адміністраторів чату."""

from __future__ import annotations

import re

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.config import Settings
from bot.db import custom_roles as db
from bot.db import groups
from bot.db.custom_roles import MAX_PER_CHAT, CustomRole
from bot.engine.models import MAX_PLAYERS, MIN_PLAYERS
from bot.engine.roles import CUSTOM_ABILITIES, CUSTOM_TEAMS, ROLES, TEAM_TITLES, Team
from bot.handlers.common import is_chat_admin, is_group

router = Router(name="roles_builder")

NAME_RE = re.compile(r"^[0-9A-Za-zА-ЩЬЮЯҐЄІЇа-щьюяґєії'’ʼ\- ]{2,24}$")
MAX_DESC = 300


class RoleCb(CallbackData, prefix="rb"):
    action: str  # list | new | open | team | abil | setab | minus | plus | toggle | name | desc | del | delok | cancel
    chat: int
    role: int = 0
    val: str = ""


class RoleInput(StatesGroup):
    name = State()
    desc = State()


def open_url(bot_username: str, chat_id: int) -> str:
    return f"https://t.me/{bot_username}?start=roles{chat_id}"


def open_keyboard(bot_username: str, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=texts.RB_OPEN_BUTTON, url=open_url(bot_username, chat_id)),
    ]])


# ---------- екрани ----------

def list_keyboard(chat_id: int, roles: list[CustomRole]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in roles:
        kb.button(text=r.name if r.enabled else f"{r.name} (вимк.)",
                  callback_data=RoleCb(action="open", chat=chat_id, role=r.id))
    kb.adjust(2)
    if len(roles) < MAX_PER_CHAT:
        kb.row(InlineKeyboardButton(text=texts.RB_CREATE, callback_data=RoleCb(action="new", chat=chat_id).pack()))
    return kb.as_markup()


def role_keyboard(r: CustomRole) -> InlineKeyboardMarkup:
    def cb(action: str, val: str = "") -> str:
        return RoleCb(action=action, chat=r.chat_id, role=r.id, val=val).pack()

    def btn(text: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=cb(action))

    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(texts.RB_NAME, "name"), btn(texts.RB_DESC, "desc")],
        [btn(f"Сторона: {TEAM_TITLES[Team(r.team)]}", "team")],
        [btn(f"Здібність: {texts.ABILITY_LABELS[r.ability]}", "abil")],
        [btn("−", "minus"), btn(f"Від {r.min_players} гравців", "open"), btn("+", "plus")],
        [btn(texts.RB_DISABLE if r.enabled else texts.RB_ENABLE, "toggle"), btn(texts.RB_DELETE, "del")],
        [btn(texts.RB_BACK_TO_LIST, "list")],
    ])


def abilities_keyboard(r: CustomRole) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key in CUSTOM_ABILITIES:
        mark = "● " if key == r.ability else ""
        kb.button(text=mark + texts.ABILITY_LABELS[key],
                  callback_data=RoleCb(action="setab", chat=r.chat_id, role=r.id, val=key))
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=texts.RB_BACK,
                                callback_data=RoleCb(action="open", chat=r.chat_id, role=r.id).pack()))
    return kb.as_markup()


def cancel_keyboard(chat_id: int, role_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=texts.RB_CANCEL, callback_data=RoleCb(action="cancel", chat=chat_id, role=role_id).pack())]])


async def list_screen(pool: asyncpg.Pool, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    roles = await db.list_for_chat(pool, chat_id)
    title = await pool.fetchval("SELECT title FROM group_settings WHERE chat_id = $1", chat_id) or str(chat_id)
    return texts.rb_list(title, roles, MAX_PER_CHAT), list_keyboard(chat_id, roles)


def valid_name(name: str) -> bool:
    if not NAME_RE.match(name) or name != name.strip():
        return False
    return name.casefold() not in {r.name.casefold() for r in ROLES.values()}


# ---------- вхід ----------

@router.message(Command("roles"))
async def cmd_roles(message: Message, bot: Bot, pool: asyncpg.Pool, config: Settings) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    if not await is_chat_admin(bot, message.chat.id, message.from_user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    await groups.get(pool, message.chat.id, message.chat.title or "")
    me = await bot.me()
    await message.answer(texts.RB_OPEN_IN_PM, reply_markup=open_keyboard(me.username, message.chat.id))


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^roles-?\d+$")), F.chat.type == "private")
async def open_via_link(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool,
                        config: Settings, state: FSMContext) -> None:
    chat_id = int(command.args[5:])
    if not await is_chat_admin(bot, chat_id, message.from_user.id, config):
        await message.answer(texts.RB_NO_RIGHTS)
        return
    await state.clear()
    text, markup = await list_screen(pool, chat_id)
    await message.answer(text, reply_markup=markup)


# ---------- кнопки ----------

async def show(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


@router.callback_query(RoleCb.filter())
async def on_role(cb: CallbackQuery, callback_data: RoleCb, bot: Bot, pool: asyncpg.Pool,
                  config: Settings, state: FSMContext) -> None:
    chat_id, action = callback_data.chat, callback_data.action
    if not await is_chat_admin(bot, chat_id, cb.from_user.id, config):
        await cb.answer(texts.RB_NO_RIGHTS, show_alert=True)
        return

    if action == "list" or (action == "cancel" and not callback_data.role):
        await state.clear()
        await cb.answer()
        await show(cb, *await list_screen(pool, chat_id))
        return
    if action == "new":
        await state.set_state(RoleInput.name)
        await state.update_data(chat=chat_id, role=0)
        await cb.answer()
        await show(cb, texts.RB_ASK_NAME, cancel_keyboard(chat_id, 0))
        return

    r = await db.get(pool, callback_data.role)
    if r is None or r.chat_id != chat_id:
        await cb.answer(texts.RB_NOT_FOUND, show_alert=True)
        await show(cb, *await list_screen(pool, chat_id))
        return

    if action in ("name", "desc"):
        await state.set_state(RoleInput.name if action == "name" else RoleInput.desc)
        await state.update_data(chat=chat_id, role=r.id)
        await cb.answer()
        await show(cb, texts.RB_ASK_NAME if action == "name" else texts.RB_ASK_DESC, cancel_keyboard(chat_id, r.id))
        return
    if action == "abil":
        await cb.answer()
        await show(cb, texts.rb_abilities(r), abilities_keyboard(r))
        return
    if action == "del":
        await cb.answer()
        await show(cb, f"Видалити роль <b>{texts.escape(r.name)}</b>?", InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=texts.RB_DELETE_CONFIRM,
                                 callback_data=RoleCb(action="delok", chat=chat_id, role=r.id).pack()),
            InlineKeyboardButton(text=texts.RB_BACK,
                                 callback_data=RoleCb(action="open", chat=chat_id, role=r.id).pack()),
        ]]))
        return
    if action == "delok":
        await db.delete(pool, r.id)
        await cb.answer(texts.RB_DELETED)
        await show(cb, *await list_screen(pool, chat_id))
        return

    if action == "team":
        teams = [t.value for t in CUSTOM_TEAMS]
        await db.update(pool, r.id, "team", teams[(teams.index(r.team) + 1) % len(teams)])
    elif action == "setab" and callback_data.val in CUSTOM_ABILITIES:
        await db.update(pool, r.id, "ability", callback_data.val)
    elif action in ("minus", "plus"):
        step = 1 if action == "plus" else -1
        await db.update(pool, r.id, "min_players", max(MIN_PLAYERS, min(MAX_PLAYERS, r.min_players + step)))
    elif action == "toggle":
        await db.update(pool, r.id, "enabled", not r.enabled)
    elif action == "cancel":
        await state.clear()
    await cb.answer()
    r = await db.get(pool, r.id)
    await show(cb, texts.rb_role(r), role_keyboard(r))


# ---------- введення тексту ----------

@router.message(StateFilter(RoleInput), F.chat.type == "private", F.text)
async def on_input(message: Message, bot: Bot, pool: asyncpg.Pool, config: Settings, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id, role_id = data["chat"], data["role"]
    if not await is_chat_admin(bot, chat_id, message.from_user.id, config):
        await state.clear()
        await message.answer(texts.RB_NO_RIGHTS)
        return
    text = message.text.strip()
    current = await state.get_state()

    if current == RoleInput.name.state:
        if not valid_name(text):
            await message.answer(texts.RB_BAD_NAME, reply_markup=cancel_keyboard(chat_id, role_id))
            return
        if role_id:
            ok = await db.update(pool, role_id, "name", text)
            error = None if ok else texts.RB_EXISTS
        else:
            created = await db.create(pool, chat_id, text, message.from_user.id)
            error = {"exists": texts.RB_EXISTS, "limit": texts.RB_LIMIT.format(max=MAX_PER_CHAT)}.get(created) \
                if isinstance(created, str) else None
            if not error:
                role_id = created.id
        if error:
            await message.answer(error, reply_markup=cancel_keyboard(chat_id, role_id))
            return
    else:
        if len(text) > MAX_DESC:
            await message.answer(texts.RB_BAD_DESC, reply_markup=cancel_keyboard(chat_id, role_id))
            return
        await db.update(pool, role_id, "description", text)

    await state.clear()
    r = await db.get(pool, role_id)
    if r is None:
        await message.answer(texts.RB_NOT_FOUND)
        return
    await message.answer(texts.rb_role(r), reply_markup=role_keyboard(r))
