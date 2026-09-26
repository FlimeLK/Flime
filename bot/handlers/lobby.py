"""Збір гравців, старт і зупинка гри."""

from __future__ import annotations

import asyncpg
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot import texts
from bot.config import Settings
from bot.db import groups
from bot.db.users import User
from bot.engine.models import MAX_PLAYERS, MIN_PLAYERS
from bot.game.manager import GameManager
from bot.handlers.common import is_chat_admin, is_group

router = Router(name="lobby")


@router.message(Command("game"))
async def cmd_game(message: Message, pool: asyncpg.Pool, manager: GameManager, user: User) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    if manager.get(message.chat.id):
        await message.answer(texts.LOBBY_ALREADY)
        return
    settings = await groups.get(pool, message.chat.id, message.chat.title or "")
    manager.create(message.chat.id, settings, user.id, message.chat.title or "")


DEFAULT_TEST_BOTS = 5


@router.message(Command("testgame"))
async def cmd_testgame(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool,
                       manager: GameManager, config: Settings, user: User) -> None:
    """Тестова гра з ботами: /testgame [скільки ботів]. Лише для адміністраторів чату."""
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    if not await is_chat_admin(bot, message.chat.id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    if manager.get(message.chat.id):
        await message.answer(texts.LOBBY_ALREADY)
        return
    arg = (command.args or "").strip()
    count = int(arg) if arg.isdigit() else DEFAULT_TEST_BOTS
    count = max(1, min(MAX_PLAYERS - 1, count))
    settings = await groups.get(pool, message.chat.id, message.chat.title or "")
    manager.create(message.chat.id, settings, user.id, message.chat.title or "", bots=count)
    await message.answer(texts.TEST_GAME_STARTED.format(bots=count))


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^join-?\d+$")), F.chat.type == "private")
async def join_via_link(message: Message, command: CommandObject, manager: GameManager, user: User) -> None:
    chat_id = int(command.args[4:])
    runner = manager.get(chat_id)
    if runner is None:
        await message.answer(texts.NO_GAME)
        return
    other = manager.runner_of_user(user.id)
    if other is not None and other is not runner:
        await message.answer(texts.JOIN_IN_OTHER)
        return
    error = runner.join(user.id, message.from_user.full_name, user.is_vip)
    if error:
        await message.answer(error)
        return
    await message.answer(texts.JOINED_PM.format(chat=texts.escape(runner.chat_title or "групі")))
    await runner.refresh_lobby()


@router.message(Command("leave"))
async def cmd_leave(message: Message, manager: GameManager, user: User) -> None:
    runner = manager.get(message.chat.id) if is_group(message) else manager.runner_of_user(user.id)
    if runner is None or not runner.leave(user.id):
        await message.answer(texts.NOT_IN_LOBBY)
        return
    await runner.m.send(runner.chat_id, texts.LEFT_LOBBY.format(name=texts.mention(user.id, user.name)))
    await runner.refresh_lobby()


@router.message(Command("start_now"))
async def cmd_start_now(message: Message, bot: Bot, manager: GameManager, config: Settings, user: User) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    runner = manager.get(message.chat.id)
    if runner is None:
        await message.answer(texts.NO_GAME)
        return
    if user.id != runner.game.starter_id and not await is_chat_admin(bot, message.chat.id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    if not runner.force_start():
        await message.answer(texts.FORCE_START_FEW.format(min=MIN_PLAYERS))


@router.message(Command("stop"))
async def cmd_stop(message: Message, bot: Bot, manager: GameManager, config: Settings, user: User) -> None:
    if not is_group(message):
        await message.answer(texts.GROUP_ONLY)
        return
    runner = manager.get(message.chat.id)
    if runner is None:
        await message.answer(texts.NO_GAME)
        return
    if not await is_chat_admin(bot, message.chat.id, user.id, config):
        await message.answer(texts.ADMIN_ONLY)
        return
    await runner.stop()
