"""Кнопки під час гри: нічні дії, голосування, підтвердження страти, рада нечисті."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from bot import texts
from bot.db.users import User
from bot.game.callbacks import ConfirmCb, HoneyCb, NightCb, VoteCb
from bot.game.manager import GameManager
from bot.handlers.common import respond

router = Router(name="play")


@router.callback_query(NightCb.filter())
async def on_night(cb: CallbackQuery, callback_data: NightCb, manager: GameManager, user: User) -> None:
    runner = manager.get(callback_data.chat)
    if runner is None:
        await cb.answer(texts.NO_GAME, show_alert=True)
        return
    await respond(cb, runner.night_action(user.id, callback_data.kind, callback_data.target))


@router.callback_query(VoteCb.filter())
async def on_vote(cb: CallbackQuery, callback_data: VoteCb, manager: GameManager, user: User) -> None:
    runner = manager.get(callback_data.chat)
    if runner is None:
        await cb.answer(texts.NO_GAME, show_alert=True)
        return
    await respond(cb, runner.vote(user.id, callback_data.target))


@router.callback_query(HoneyCb.filter())
async def on_honey(cb: CallbackQuery, callback_data: HoneyCb, manager: GameManager, user: User) -> None:
    runner = manager.get(callback_data.chat)
    if runner is None:
        await cb.answer(texts.NO_GAME, show_alert=True)
        return
    await respond(cb, runner.honey(user.id))


@router.callback_query(ConfirmCb.filter())
async def on_confirm(cb: CallbackQuery, callback_data: ConfirmCb, manager: GameManager, user: User) -> None:
    runner = manager.get(callback_data.chat)
    if runner is None:
        await cb.answer(texts.NO_GAME, show_alert=True)
        return
    reply = runner.confirm_vote(user.id, bool(callback_data.yes))
    await cb.answer(reply.text, show_alert=reply.alert)


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"), StateFilter(None))
async def evil_council(message: Message, manager: GameManager, user: User) -> None:
    runner = manager.runner_of_user(user.id)
    if runner is None:
        return
    targets = runner.evil_chat_targets(user.id)
    if not targets:
        return
    text = texts.EVIL_CHAT.format(name=texts.escape(user.name), text=texts.escape(message.text))
    for uid in targets:
        await runner.m.send(uid, text)
