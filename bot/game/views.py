"""Клавіатури гри."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.engine.models import Game
from bot.engine.night import can_target
from bot.engine.roles import NightKind
from bot.game.callbacks import ConfirmCb, HoneyCb, NightCb, VoteCb


def join_keyboard(bot_username: str, chat_id: int) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}?start=join{chat_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.JOIN_BUTTON, url=url)],
        [InlineKeyboardButton(text=texts.RULES_BUTTON, url=f"https://t.me/{bot_username}?start=rules")],
    ])


def to_bot_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=texts.TO_BOT_BUTTON, url=f"https://t.me/{bot_username}"),
    ]])


def night_targets(game: Game, actor: int, kind: NightKind, exclude: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in game.alive():
        if p.user_id == exclude:
            continue
        if can_target(game, actor, kind, p.user_id):
            kb.button(text=p.name[:32], callback_data=NightCb(chat=game.chat_id, kind=kind.value, target=p.user_id))
    kb.adjust(2)
    if kind in (NightKind.SABER, NightKind.PITCHFORK):
        kb.row(InlineKeyboardButton(
            text=texts.SKIP_BUTTON,
            callback_data=NightCb(chat=game.chat_id, kind=kind.value, target=0).pack(),
        ))
    return kb.as_markup()


def compare_second(game: Game, actor: int, first: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in game.alive():
        if p.user_id not in (actor, first):
            kb.button(text=p.name[:32], callback_data=NightCb(chat=game.chat_id, kind="compare2", target=p.user_id))
    kb.adjust(2)
    return kb.as_markup()


def vote_keyboard(game: Game, voter: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in game.alive():
        if p.user_id != voter:
            kb.button(text=p.name[:32], callback_data=VoteCb(chat=game.chat_id, target=p.user_id))
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=texts.SKIP_BUTTON, callback_data=VoteCb(chat=game.chat_id, target=0).pack()))
    player = game.players[voter]
    if player.has("honey") and voter not in game.honey_voters:
        kb.row(InlineKeyboardButton(text=texts.HONEY_BUTTON, callback_data=HoneyCb(chat=game.chat_id).pack()))
    return kb.as_markup()


def confirm_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=texts.CONFIRM_YES, callback_data=ConfirmCb(chat=chat_id, yes=1).pack()),
        InlineKeyboardButton(text=texts.CONFIRM_NO, callback_data=ConfirmCb(chat=chat_id, yes=0).pack()),
    ]])
