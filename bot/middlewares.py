"""Middleware: реєстрація гравця в БД і блок-лист."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, TelegramObject

from bot import texts
from bot.db import users


class UserMiddleware(BaseMiddleware):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = None
        if isinstance(event, (Message, CallbackQuery, PreCheckoutQuery)):
            tg_user = event.from_user
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        user = await users.upsert(self.pool, tg_user.id, tg_user.full_name, tg_user.username)
        if user.blocked:
            if isinstance(event, CallbackQuery):
                await event.answer(texts.BLOCKED, show_alert=True)
            elif isinstance(event, Message) and event.chat.type == "private":
                await event.answer(texts.BLOCKED)
            return None
        data["user"] = user
        return await handler(event, data)
