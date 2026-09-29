"""Емодзі на рівні запитів бота.

1. Перед надсиланням мітки :ключ: у текстах замінюються на анімовані емодзі (або звичайні там,
   де HTML не працює: спливні вікна, рахунки).
2. Якщо Telegram відхилив запит з custom emoji (невалідний ID, власник без Premium тощо),
   той самий запит повторюється зі звичайними емодзі.
Працює для всіх запитів бота, тож окремо в хендлерах про це думати не треба.
"""

from __future__ import annotations

import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.ui.emoji import TAG_RE, render, strip

log = logging.getLogger(__name__)

TEXT_FIELDS = ("text", "caption")
# Поля без HTML - лише звичайні емодзі.
PLAIN_FIELDS = ("error_message", "title", "description")
PLAIN_METHODS = ("AnswerCallbackQuery", "AnswerPreCheckoutQuery", "SendInvoice", "CreateInvoiceLink")
# Помилки, які точно не пов'язані з емодзі - не повторюємо.
UNRELATED = ("message is not modified", "message to edit not found", "chat not found",
             "query is too old", "message can't be edited", "not enough rights")


def _markup_has_icons(markup) -> bool:
    if isinstance(markup, InlineKeyboardMarkup):
        return any(b.icon_custom_emoji_id for row in markup.inline_keyboard for b in row)
    if isinstance(markup, ReplyKeyboardMarkup):
        return any(getattr(b, "icon_custom_emoji_id", None) for row in markup.keyboard for b in row)
    return False


def _strip_markup(markup):
    if isinstance(markup, InlineKeyboardMarkup):
        return InlineKeyboardMarkup(inline_keyboard=[
            [b.model_copy(update={"icon_custom_emoji_id": None}) for b in row] for row in markup.inline_keyboard
        ])
    return markup


def has_custom_emoji(method: TelegramMethod) -> bool:
    for f in TEXT_FIELDS:
        value = getattr(method, f, None)
        if isinstance(value, str) and TAG_RE.search(value):
            return True
    return _markup_has_icons(getattr(method, "reply_markup", None))


def without_custom_emoji(method: TelegramMethod) -> TelegramMethod:
    update = {}
    for f in TEXT_FIELDS:
        value = getattr(method, f, None)
        if isinstance(value, str):
            update[f] = strip(value)
    if getattr(method, "reply_markup", None) is not None:
        update["reply_markup"] = _strip_markup(method.reply_markup)
    return method.model_copy(update=update)


def rendered(method: TelegramMethod) -> TelegramMethod:
    plain_only = type(method).__name__ in PLAIN_METHODS
    update = {}
    for f in TEXT_FIELDS + (PLAIN_FIELDS if plain_only else ()):
        value = getattr(method, f, None)
        if isinstance(value, str) and ":" in value:
            new = render(value, html=not plain_only and f in TEXT_FIELDS)
            if new != value:
                update[f] = new
    return method.model_copy(update=update) if update else method


class CustomEmojiFallback(BaseRequestMiddleware):
    async def __call__(self, make_request: NextRequestMiddlewareType, bot, method: TelegramMethod):
        method = rendered(method)
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as e:
            text = str(e).lower()
            if not has_custom_emoji(method) or any(u in text for u in UNRELATED):
                raise
            log.warning("Custom emoji rejected by Telegram (%s), resending plain: %s", type(method).__name__, e)
            return await make_request(bot, without_custom_emoji(method))
