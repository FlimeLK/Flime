"""Точка входу: python -m bot"""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from bot.config import load_settings
from bot.db.pool import create_pool
from bot.game.manager import GameManager
from bot.game.messenger import Messenger
from bot.handlers import build_router
from bot.middlewares import UserMiddleware

log = logging.getLogger("bot")

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Головне меню"),
    BotCommand(command="profile", description="Моя хата і гаманець"),
    BotCommand(command="shop", description="Ярмарок предметів"),
    BotCommand(command="daily", description="Щоденний гостинець"),
    BotCommand(command="vip", description="VIP і червінці"),
    BotCommand(command="promo", description="Активувати промокод"),
    BotCommand(command="rules", description="Правила та ролі"),
]
GROUP_COMMANDS = [
    BotCommand(command="game", description="Почати збір на гру"),
    BotCommand(command="start_now", description="Почати гру негайно"),
    BotCommand(command="leave", description="Вийти з реєстрації"),
    BotCommand(command="stop", description="Зупинити гру (адмін)"),
    BotCommand(command="settings", description="Налаштування гри (адмін)"),
    BotCommand(command="top", description="Найкращі гравці чату"),
    BotCommand(command="rules", description="Правила та ролі"),
]


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    file = RotatingFileHandler("bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    root.addHandler(file)


async def main() -> None:
    setup_logging()
    config = load_settings()
    pool = await create_pool(config.dsn)
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()

    manager = GameManager(Messenger(bot), pool, me.username)
    dp = Dispatcher(pool=pool, manager=manager, config=config)
    user_mw = UserMiddleware(pool)
    dp.message.outer_middleware(user_mw)
    dp.callback_query.outer_middleware(user_mw)
    dp.pre_checkout_query.outer_middleware(user_mw)
    dp.include_router(build_router())

    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())

    restored = await manager.restore()
    log.info("Bot @%s started, restored games: %d", me.username, restored)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await manager.shutdown()
        await pool.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
