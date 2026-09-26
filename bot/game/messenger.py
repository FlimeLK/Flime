"""Тонка обгортка над Bot: надсилання без падінь гри через помилки Telegram."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from bot.engine.models import is_bot_player

log = logging.getLogger(__name__)


class Messenger:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send(self, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> int | None:
        if is_bot_player(chat_id):
            return None  # ботам тестової гри нічого не надсилаємо
        for attempt in range(2):
            try:
                msg = await self.bot.send_message(
                    chat_id, text, reply_markup=markup, disable_web_page_preview=True
                )
                return msg.message_id
            except TelegramRetryAfter as e:
                if attempt == 0:
                    await asyncio.sleep(e.retry_after)
                    continue
                log.warning("send to %s rate-limited", chat_id)
            except TelegramAPIError as e:
                log.info("send to %s failed: %s", chat_id, e)
                return None
        return None

    async def edit(self, chat_id: int, message_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        if is_bot_player(chat_id):
            return
        try:
            await self.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as e:
            log.debug("edit %s/%s failed: %s", chat_id, message_id, e)

    async def clear_markup(self, chat_id: int, message_id: int) -> None:
        try:
            await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramAPIError as e:
            log.debug("clear markup %s/%s failed: %s", chat_id, message_id, e)
