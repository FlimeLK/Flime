"""Клавіатури головного меню, розділів і налаштувань чату.

callback_data з префіксами:
  menu:<дія>                  — головне меню (menu:main)
  sec:<розділ>                — розділ меню (sec:howto, sec:roles, …)
  set:<дія>:<ключ>:<зміна>    — налаштування чату для адмінів
Ігрові клавіатури (ніч, голосування, вирок) — у bot/game/views.py.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup

from bot import texts
from bot.db.groups import TIMER_LIMITS, GroupSettings
from bot.engine.roles import ROLES
from bot.ui.buttons import DANGER, PRIMARY, SUCCESS, btn, rows


class MenuCb(CallbackData, prefix="menu"):
    action: str


class SecCb(CallbackData, prefix="sec"):
    name: str


class SetCb(CallbackData, prefix="set"):
    # home | refresh | timers | roles | vote | items | timer | toggle | role | noop
    action: str
    key: str = ""
    delta: int = 0


# ---------- головне меню і розділи ----------

def main_menu(bot_username: str) -> InlineKeyboardMarkup:
    name, emo, label = texts.MENU_WIDE_TOP
    grid = [btn(lbl, SecCb(name=key), emo=e) for key, e, lbl in texts.MENU_GRID]
    add_emo, add_label = texts.MENU_ADD_GROUP
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(label, SecCb(name=name), emo=emo, style=PRIMARY)],
        *rows(grid, 2),
        [btn(add_label, url=f"https://t.me/{bot_username}?startgroup=true", emo=add_emo, style=SUCCESS)],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn(texts.BACK, MenuCb(action="main"), emo="back")]])


# ---------- налаштування чату ----------

def _back_to_settings() -> list:
    return [btn(texts.BACK, SetCb(action="home"), emo="back")]


def settings_home() -> InlineKeyboardMarkup:
    grid = [btn(label, SetCb(action=key), emo=emo) for key, emo, label in texts.SETTINGS_MODULES]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(grid, 2),
        [btn(texts.SETTINGS_REFRESH, SetCb(action="refresh"), emo="refresh", style=PRIMARY)],
    ])


def settings_timers(s: GroupSettings) -> InlineKeyboardMarkup:
    keyboard = []
    for key, (emo, label) in texts.TIMER_NAMES.items():
        step = TIMER_LIMITS[key][2]
        keyboard.append([
            btn("−", SetCb(action="timer", key=key, delta=-step)),
            btn(f"{label}: {texts.fmt_seconds(getattr(s, key))}", SetCb(action="noop"), emo=emo),
            btn("+", SetCb(action="timer", key=key, delta=step)),
        ])
    keyboard.append(_back_to_settings())
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def settings_roles(s: GroupSettings) -> InlineKeyboardMarkup:
    buttons = [
        btn(f"{r.name} ({r.min_players}+)", SetCb(action="role", key=r.key), emo=r.key,
            style=DANGER if r.key in s.disabled_roles else SUCCESS)
        for r in ROLES.values() if r.optional
    ]
    return InlineKeyboardMarkup(inline_keyboard=[*rows(buttons, 2), _back_to_settings()])


def settings_toggles(s: GroupSettings, keys: tuple[str, ...]) -> InlineKeyboardMarkup:
    keyboard = []
    for key in keys:
        on = bool(getattr(s, key))
        emo, label = texts.TOGGLE_LABELS[key][int(on)]
        keyboard.append([btn(label, SetCb(action="toggle", key=key), emo=emo, style=SUCCESS if on else None)])
    keyboard.append(_back_to_settings())
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
