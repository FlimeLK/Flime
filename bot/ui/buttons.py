"""Кнопки з анімованою іконкою та кольором."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton

from bot.ui.emoji import icon, plain

PRIMARY = "primary"   # синя
SUCCESS = "success"   # зелена
DANGER = "danger"     # червона


def btn(
    text: str,
    cb: CallbackData | str | None = None,
    *,
    url: str | None = None,
    emo: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    """Кнопка. `emo` - ключ з bot.ui.emoji: анімована іконка перед текстом.

    Якщо анімації немає (ID не задано або вимкнено), перед текстом без пробілу ставиться
    звичайний символ: «💬Як зі мною говорити».
    """
    icon_id = icon(emo)
    label = text if icon_id or not emo else f"{plain(emo)}{text}"
    kwargs: dict = {"text": label or " "}
    if icon_id:
        kwargs["icon_custom_emoji_id"] = icon_id
    if style:
        kwargs["style"] = style
    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = cb.pack() if isinstance(cb, CallbackData) else cb
    return InlineKeyboardButton(**kwargs)


def rows(buttons: list[InlineKeyboardButton], width: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + width] for i in range(0, len(buttons), width)]
