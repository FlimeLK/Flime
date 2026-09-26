# -*- coding: utf-8 -*-
"""
Єдине джерело правди для меню «/» у приватних чатах.

Базовий список + динамічні команди активного сезонного івенту
(напр. /kupala під час «Купальської ночі»). Викликається на старті бота
і при вмиканні/вимиканні івенту в адмін-панелі — тож меню оновлюється для всіх.
"""

from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
from commands import seasonal_events as seasonal_mod

# Базові команди ПП (раніше жили в run.py).
BASE_PRIVATE_COMMANDS = [
    BotCommand(command="start", description="🤖 Запуск бота"),
    BotCommand(command="help", description="🆘 Допомога"),
    BotCommand(command="profile", description="👤 Мій профіль"),
    BotCommand(command="promocode", description="🎟 Ввести промокод"),
    BotCommand(command="contraband", description="📦 Контрабанда"),
    BotCommand(command="leave", description="🚪 Покинути гру"),
]

# Додаткові команди ПП, що з'являються лише коли активний відповідний івент.
EVENT_PRIVATE_COMMANDS = {
    "kupala_night": [
        BotCommand(command="kupala", description="☀️ Купальська ніч"),
    ],
}


async def build_private_commands() -> list:
    """Базовий список + команди активного івенту."""
    cmds = list(BASE_PRIVATE_COMMANDS)
    try:
        active = await seasonal_mod.get_active_event_id()
    except Exception:
        active = None
    cmds += EVENT_PRIVATE_COMMANDS.get(active, [])
    return cmds


async def apply_private_commands(bot) -> None:
    """Встановити меню команд для приватних чатів (усі мови інтерфейсу)."""
    cmds = await build_private_commands()
    for lang in (None, "uk", "ru"):
        kw = {"language_code": lang} if lang else {}
        try:
            await bot.set_my_commands(cmds, scope=BotCommandScopeAllPrivateChats(), **kw)
        except Exception:
            pass
