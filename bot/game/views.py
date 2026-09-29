"""Клавіатури гри: анімовані іконки та кольори кнопок."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot import texts
from bot.engine.models import Game
from bot.engine.night import can_target
from bot.engine.roles import NightKind
from bot.game.callbacks import ConfirmCb, HoneyCb, NightCb, VoteCb
from bot.ui.buttons import DANGER, PRIMARY, SUCCESS, btn, rows

# Колір і іконка кнопок цілей для кожної нічної дії.
NIGHT_STYLE: dict[NightKind, tuple[str, str | None]] = {
    NightKind.KILL: ("evil", DANGER),
    NightKind.WOLF_KILL: ("vovkulaka", DANGER),
    NightKind.SABER: ("harakternyk", DANGER),
    NightKind.PITCHFORK: ("pitchfork", DANGER),
    NightKind.HEAL: ("heal", SUCCESS),
    NightKind.CHECK: ("check", PRIMARY),
    NightKind.COMPARE: ("kobzar", PRIMARY),
    NightKind.WATCH: ("eye", PRIMARY),
    NightKind.LURE: ("mavka", None),
}


def join_keyboard(bot_username: str, chat_id: int) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}?start=join{chat_id}"
    return InlineKeyboardMarkup(inline_keyboard=[[btn(texts.JOIN_BUTTON, url=url, emo="hand", style=SUCCESS)]])


def night_targets(game: Game, actor: int, kind: NightKind) -> InlineKeyboardMarkup:
    emo, style = NIGHT_STYLE.get(kind, (None, None))
    buttons = [
        btn(p.name[:32], NightCb(chat=game.chat_id, kind=kind.value, target=p.user_id), emo=emo, style=style)
        for p in game.alive()
        if can_target(game, actor, kind, p.user_id)
    ]
    keyboard = rows(buttons, 2)
    if kind in (NightKind.SABER, NightKind.PITCHFORK):
        keyboard.append([btn(texts.SKIP_BUTTON, NightCb(chat=game.chat_id, kind=kind.value, target=0), emo="skip")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def compare_second(game: Game, actor: int, first: int) -> InlineKeyboardMarkup:
    buttons = [
        btn(p.name[:32], NightCb(chat=game.chat_id, kind="compare2", target=p.user_id), emo="kobzar", style=PRIMARY)
        for p in game.alive()
        if p.user_id not in (actor, first)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows(buttons, 2))


def vote_keyboard(game: Game, voter: int) -> InlineKeyboardMarkup:
    buttons = [
        btn(p.name[:32], VoteCb(chat=game.chat_id, target=p.user_id), emo="rope", style=DANGER)
        for p in game.alive()
        if p.user_id != voter
    ]
    keyboard = rows(buttons, 2)
    keyboard.append([btn(texts.SKIP_BUTTON, VoteCb(chat=game.chat_id, target=0), emo="dove")])
    player = game.players[voter]
    if player.has("honey") and voter not in game.honey_voters:
        keyboard.append([btn(texts.HONEY_BUTTON, HoneyCb(chat=game.chat_id), emo="honey", style=SUCCESS)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def confirm_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        btn(texts.CONFIRM_YES, ConfirmCb(chat=chat_id, yes=1), emo="like", style=DANGER),
        btn(texts.CONFIRM_NO, ConfirmCb(chat=chat_id, yes=0), emo="dislike", style=SUCCESS),
    ]])
