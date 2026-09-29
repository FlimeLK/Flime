"""Тонка обгортка над Bot: надсилання без падінь гри через помилки Telegram."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message

from bot.ui import media

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
_TAGS = re.compile(r"<[^>]+>")


def visible_len(html: str) -> int:
    return len(_TAGS.sub("", html))


class Messenger:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def _call(self, chat_id: int, make: Callable[[], Awaitable[Message]]) -> int | None:
        for attempt in range(2):
            try:
                msg = await make()
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

    async def send(
        self,
        chat_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
        effect: str | None = None,
    ) -> int | None:
        effect = effect if chat_id > 0 else None  # ефекти - лише в особистих
        return await self._call(chat_id, lambda: self.bot.send_message(
            chat_id, text, reply_markup=markup, disable_web_page_preview=True, message_effect_id=effect,
        ))

    async def send_scene(
        self,
        chat_id: int,
        slot: str,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
        effect: str | None = None,
    ) -> int | None:
        """Повідомлення з медіа сцени (якщо власник його завантажив), інакше звичайний текст.

        Повертає message_id повідомлення з текстом (його можна редагувати).
        """
        item = media.get(slot)
        if item is None:
            return await self.send(chat_id, text, markup, effect)
        kind, file_id = item
        effect = effect if chat_id > 0 else None
        sender = {"photo": self.bot.send_photo, "animation": self.bot.send_animation,
                  "video": self.bot.send_video}[kind]
        if visible_len(text) <= CAPTION_LIMIT:
            mid = await self._call(chat_id, lambda: sender(
                chat_id, file_id, caption=text, reply_markup=markup, message_effect_id=effect))
            if mid is not None:
                return mid
            # Медіа не надіслалось (наприклад, file_id застарів) - хоча б текст.
            return await self.send(chat_id, text, markup, effect)
        await self._call(chat_id, lambda: sender(chat_id, file_id, message_effect_id=effect))
        return await self.send(chat_id, text, markup)

    async def edit(self, chat_id: int, message_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await self.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as e:
            if "there is no text in the message" in str(e).lower():
                # Це повідомлення з медіа - редагуємо підпис.
                try:
                    await self.bot.edit_message_caption(
                        chat_id=chat_id, message_id=message_id, caption=text, reply_markup=markup)
                except TelegramAPIError as e2:
                    log.debug("edit caption %s/%s failed: %s", chat_id, message_id, e2)
                return
            log.debug("edit %s/%s failed: %s", chat_id, message_id, e)

    async def clear_markup(self, chat_id: int, message_id: int) -> None:
        try:
            await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramAPIError as e:
            log.debug("clear markup %s/%s failed: %s", chat_id, message_id, e)

    async def pin(self, chat_id: int, message_id: int) -> None:
        try:
            await self.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
        except TelegramAPIError as e:  # у бота немає права закріплювати
            log.debug("pin %s/%s failed: %s", chat_id, message_id, e)

    async def unpin(self, chat_id: int, message_id: int) -> None:
        try:
            await self.bot.unpin_chat_message(chat_id, message_id=message_id)
        except TelegramAPIError as e:
            log.debug("unpin %s/%s failed: %s", chat_id, message_id, e)
