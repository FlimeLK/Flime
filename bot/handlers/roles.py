"""Власні ролі чату: покроковий майстер і керування в особистих з ботом.

Адмін потрапляє сюди з панелі налаштувань (кнопки «Створити роль» / «Мої ролі») або через deep-link:
  t.me/<bot>?start=newrole<chat_id>  - створити роль
  t.me/<bot>?start=myroles<chat_id>  - мої ролі
"""

from __future__ import annotations

import re

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards, texts
from bot.config import Settings
from bot.db import roles as roles_db
from bot.db.users import User
from bot.engine.roles import ABILITIES
from bot.handlers.common import is_chat_admin
from bot.keyboards import RoleCb

router = Router(name="roles")
router.message.filter(F.chat.type == "private")

DEEP_LINK = re.compile(r"^(newrole|myroles)(-?\d+)$")


class RoleForm(StatesGroup):
    name = State()
    emoji = State()
    description = State()
    team = State()
    ability = State()
    min_players = State()
    confirm = State()


async def chat_title(pool: asyncpg.Pool, chat_id: int) -> str:
    title = await pool.fetchval("SELECT title FROM group_settings WHERE chat_id = $1", chat_id)
    return texts.escape(title or str(chat_id))


def emoji_html(data: dict) -> str:
    if data.get("emoji_id"):
        return f'<tg-emoji emoji-id="{data["emoji_id"]}">{data["emoji"]}</tg-emoji>'
    return data["emoji"]


# ---------- вхід через deep-link ----------

@router.message(CommandStart(deep_link=True, magic=F.args.regexp(DEEP_LINK.pattern)))
async def roles_entry(message: Message, command: CommandObject, state: FSMContext, bot: Bot,
                      pool: asyncpg.Pool, config: Settings, user: User) -> None:
    kind, raw_chat = DEEP_LINK.match(command.args).groups()
    chat_id = int(raw_chat)
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await message.answer(texts.ROLES_NOT_ADMIN)
        return
    await state.clear()
    if kind == "myroles":
        await show_list(message, pool, chat_id)
        return
    await start_wizard(message, state, pool, chat_id)


async def start_wizard(message: Message, state: FSMContext, pool: asyncpg.Pool, chat_id: int) -> None:
    if await roles_db.count(pool, chat_id) >= roles_db.MAX_PER_CHAT:
        await message.answer(texts.ROLES_LIMIT.format(max=roles_db.MAX_PER_CHAT),
                             reply_markup=keyboards.role_done(chat_id))
        return
    await state.set_state(RoleForm.name)
    await state.update_data(chat_id=chat_id)
    await message.answer(texts.ROLE_STEP_NAME.format(chat=await chat_title(pool, chat_id)))


@router.callback_query(RoleCb.filter(F.action == "new"))
async def on_new(cb: CallbackQuery, callback_data: RoleCb, state: FSMContext, bot: Bot, pool: asyncpg.Pool,
                 config: Settings, user: User) -> None:
    chat_id = int(callback_data.value) if callback_data.value.lstrip("-").isdigit() else 0
    if not chat_id or not await is_chat_admin(bot, chat_id, user.id, config):
        await cb.answer(texts.ROLES_NOT_ADMIN, show_alert=True)
        return
    await cb.answer()
    await state.clear()
    await start_wizard(cb.message, state, pool, chat_id)


@router.message(Command("cancel"), StateFilter(RoleForm))
async def cancel_cmd(message: Message, state: FSMContext) -> None:
    chat_id = (await state.get_data()).get("chat_id")
    await state.clear()
    await message.answer(texts.ROLE_CANCELLED, reply_markup=keyboards.role_done(chat_id) if chat_id else None)


# ---------- кроки майстра ----------

@router.message(RoleForm.name, F.text)
async def step_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not 1 <= len(name) <= 24 or name.startswith("/"):
        await message.answer(texts.ROLE_BAD_NAME)
        return
    await state.update_data(name=name)
    await state.set_state(RoleForm.emoji)
    await message.answer(texts.ROLE_STEP_EMOJI)


@router.message(RoleForm.emoji, F.text)
async def step_emoji(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    premium = [e for e in (message.entities or []) if e.type == "custom_emoji"]
    if premium:
        emoji, emoji_id = premium[0].extract_from(message.text), premium[0].custom_emoji_id
    elif text and len(text) <= 8 and not any(ch.isalnum() for ch in text):
        emoji, emoji_id = text, None
    else:
        await message.answer(texts.ROLE_BAD_EMOJI)
        return
    await state.update_data(emoji=emoji, emoji_id=emoji_id)
    await state.set_state(RoleForm.description)
    await message.answer(texts.ROLE_STEP_DESC)


@router.message(RoleForm.description, F.text)
async def step_description(message: Message, state: FSMContext) -> None:
    desc = message.text.strip()
    if not 1 <= len(desc) <= 200 or desc.startswith("/"):
        await message.answer(texts.ROLE_BAD_DESC)
        return
    await state.update_data(description=desc)
    await state.set_state(RoleForm.team)
    options = [(key, emo, label) for key, (emo, label) in texts.ROLE_TEAM_LABELS.items()]
    await message.answer(texts.ROLE_STEP_TEAM, reply_markup=keyboards.role_choice("team", options, 3))


async def _edit(cb: CallbackQuery, text: str, markup=None) -> None:
    await cb.answer()
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup)


@router.callback_query(RoleCb.filter(F.action == "team"), RoleForm.team)
async def step_team(cb: CallbackQuery, callback_data: RoleCb, state: FSMContext) -> None:
    if callback_data.value not in texts.ROLE_TEAM_LABELS:
        await cb.answer()
        return
    await state.update_data(team=callback_data.value)
    await state.set_state(RoleForm.ability)
    options = [(key, texts.ROLE_ABILITY_EMO[key], label) for key, label in ABILITIES.items()]
    hints = "\n".join(f":{texts.ROLE_ABILITY_EMO[k]}: <b>{ABILITIES[k]}</b> - {h}"
                      for k, h in texts.ROLE_ABILITY_HINTS.items())
    await _edit(cb, f"{texts.ROLE_STEP_ABILITY}\n\n{hints}", keyboards.role_choice("ability", options, 2))


@router.callback_query(RoleCb.filter(F.action == "ability"), RoleForm.ability)
async def step_ability(cb: CallbackQuery, callback_data: RoleCb, state: FSMContext) -> None:
    if callback_data.value not in ABILITIES:
        await cb.answer()
        return
    await state.update_data(ability=callback_data.value)
    await state.set_state(RoleForm.min_players)
    options = [(str(n), "", f"{n}+") for n in texts.ROLE_MIN_PLAYERS]
    await _edit(cb, texts.ROLE_STEP_MIN, keyboards.role_choice("min", options, 4))


@router.callback_query(RoleCb.filter(F.action == "min"), RoleForm.min_players)
async def step_min(cb: CallbackQuery, callback_data: RoleCb, state: FSMContext) -> None:
    if not callback_data.value.isdigit() or int(callback_data.value) not in texts.ROLE_MIN_PLAYERS:
        await cb.answer()
        return
    await state.update_data(min_players=int(callback_data.value))
    await state.set_state(RoleForm.confirm)
    d = await state.get_data()
    preview = texts.role_preview(d["name"], emoji_html(d), d["description"], d["team"], d["ability"],
                                 d["min_players"])
    await _edit(cb, preview, keyboards.role_confirm())


@router.callback_query(RoleCb.filter(F.action == "save"), RoleForm.confirm)
async def step_save(cb: CallbackQuery, state: FSMContext, bot: Bot, pool: asyncpg.Pool,
                    config: Settings, user: User) -> None:
    d = await state.get_data()
    await state.clear()
    if not await is_chat_admin(bot, d["chat_id"], user.id, config):
        await _edit(cb, texts.ROLES_NOT_ADMIN)
        return
    if await roles_db.count(pool, d["chat_id"]) >= roles_db.MAX_PER_CHAT:
        await _edit(cb, texts.ROLES_LIMIT.format(max=roles_db.MAX_PER_CHAT))
        return
    await roles_db.create(
        pool, d["chat_id"], user.id, name=d["name"], emoji=d["emoji"], emoji_id=d.get("emoji_id"),
        description=d["description"], team=d["team"], ability=d["ability"], min_players=d["min_players"],
    )
    title = f"{emoji_html(d)} <b>{texts.escape(d['name'])}</b>"
    await _edit(cb, texts.ROLE_SAVED.format(title=title), keyboards.role_done(d["chat_id"]))


@router.callback_query(RoleCb.filter(F.action == "cancel"))
async def step_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = (await state.get_data()).get("chat_id")
    await state.clear()
    await _edit(cb, texts.ROLE_CANCELLED, keyboards.role_done(chat_id) if chat_id else None)


# ---------- мої ролі ----------

async def show_list(message: Message, pool: asyncpg.Pool, chat_id: int, edit: bool = False) -> None:
    custom = await roles_db.list_for_chat(pool, chat_id)
    markup = keyboards.roles_list(custom, chat_id)
    if not custom:
        text = texts.ROLES_EMPTY
    else:
        text = texts.ROLES_LIST_HEAD.format(chat=await chat_title(pool, chat_id))
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, reply_markup=markup)


async def _owned_role(cb: CallbackQuery, value: str, bot: Bot, pool: asyncpg.Pool, config: Settings,
                      user: User) -> dict | None:
    role = await roles_db.get(pool, int(value)) if value.isdigit() else None
    if role is None or not await is_chat_admin(bot, role["chat_id"], user.id, config):
        await cb.answer(texts.ROLES_NOT_ADMIN, show_alert=True)
        return None
    return role


@router.callback_query(RoleCb.filter(F.action == "list"))
async def on_list(cb: CallbackQuery, callback_data: RoleCb, bot: Bot, pool: asyncpg.Pool,
                  config: Settings, user: User) -> None:
    chat_id = int(callback_data.value) if callback_data.value.lstrip("-").isdigit() else 0
    if not await is_chat_admin(bot, chat_id, user.id, config):
        await cb.answer(texts.ROLES_NOT_ADMIN, show_alert=True)
        return
    await cb.answer()
    await show_list(cb.message, pool, chat_id, edit=True)


@router.callback_query(RoleCb.filter(F.action == "view"))
async def on_view(cb: CallbackQuery, callback_data: RoleCb, bot: Bot, pool: asyncpg.Pool,
                  config: Settings, user: User) -> None:
    role = await _owned_role(cb, callback_data.value, bot, pool, config, user)
    if role:
        preview = texts.role_preview(role["name"], emoji_html(role), role["description"], role["team"],
                                     role["ability"], role["min_players"])
        status = "\n\n:ok: У грі" if role["enabled"] else "\n\n:no: Вимкнена"
        await _edit(cb, preview + status, keyboards.role_manage(role))


@router.callback_query(RoleCb.filter(F.action == "toggle"))
async def on_toggle(cb: CallbackQuery, callback_data: RoleCb, bot: Bot, pool: asyncpg.Pool,
                    config: Settings, user: User) -> None:
    role = await _owned_role(cb, callback_data.value, bot, pool, config, user)
    if role:
        await roles_db.toggle(pool, role["id"])
        await on_view(cb, callback_data, bot, pool, config, user)


@router.callback_query(RoleCb.filter(F.action == "delete"))
async def on_delete(cb: CallbackQuery, callback_data: RoleCb, bot: Bot, pool: asyncpg.Pool,
                    config: Settings, user: User) -> None:
    role = await _owned_role(cb, callback_data.value, bot, pool, config, user)
    if role:
        await roles_db.delete(pool, role["id"])
        await cb.answer(texts.ROLE_DELETED)
        await show_list(cb.message, pool, role["chat_id"], edit=True)
