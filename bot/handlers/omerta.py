"""Омерта (закон мовчання): під час гри бот видаляє повідомлення мертвих і, за бажанням, усіх гравців уночі.

Вмикається в /settings → Омерта. Боту потрібні права адміна з видаленням повідомлень.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Filter
from aiogram.types import Message

from bot.engine.models import Phase
from bot.game.manager import GameManager
from bot.handlers.common import GROUP_TYPES

router = Router(name="omerta")


class MustBeSilent(Filter):
    """Спрацьовує лише на повідомлення, які закон мовчання забороняє; решта йде далі по роутерах."""

    async def __call__(self, message: Message, manager: GameManager) -> bool:
        if message.chat.type not in GROUP_TYPES or message.from_user is None:
            return False
        if (message.text or "").startswith("/"):
            return False  # команди (/stop, /leave) завжди проходять
        runner = manager.get(message.chat.id)
        if runner is None:
            return False
        g = runner.game
        player = g.players.get(message.from_user.id)
        if player is None or g.phase in (Phase.LOBBY, Phase.FINISHED):
            return False
        if not player.alive:
            return bool(g.settings.get("omerta_dead"))
        return g.phase == Phase.NIGHT and bool(g.settings.get("omerta_night"))


@router.message(MustBeSilent())
async def silence(message: Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError:
        pass  # у бота немає права видаляти
