"""Спільні помічники для обробників."""

from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.game.runner import Reply

GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


def is_group(message: Message) -> bool:
    return message.chat.type in GROUP_TYPES


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int, config: Settings) -> bool:
    if user_id in config.owner_ids:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramBadRequest:
        return False
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def respond(cb: CallbackQuery, reply: Reply) -> None:
    """Відповідь на натискання кнопки в особистих: спливне вікно або заміна тексту."""
    if reply.alert:
        await cb.answer(reply.text, show_alert=True)
        return
    await cb.answer()
    if cb.message:
        try:
            await cb.message.edit_text(reply.text, reply_markup=reply.markup)
        except TelegramBadRequest:
            pass
