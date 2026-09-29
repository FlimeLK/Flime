"""Клавіатури головного меню, розділів і налаштувань чату.

callback_data з префіксами:
  menu:<дія>                  - головне меню (menu:main)
  sec:<розділ>                - розділ меню (sec:howto, sec:roles, …)
  set:<дія>:<ключ>:<зміна>    - налаштування чату для адмінів
Ігрові клавіатури (ніч, голосування, вирок) - у bot/game/views.py.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup

from bot import texts
from bot.db.groups import PLAYER_LIMITS, TIMER_LIMITS, GroupSettings
from bot.engine.items import ITEMS
from bot.engine.roles import ROLES
from bot.ui.buttons import DANGER, PRIMARY, SUCCESS, btn, rows


class MenuCb(CallbackData, prefix="menu"):
    action: str


class SecCb(CallbackData, prefix="sec"):
    name: str


class SetCb(CallbackData, prefix="set"):
    # home | refresh | timers | timer | roles | role | crole | vote | items | item | omerta | family | ratio
    # | players | lobby | toggle | reset | reset_ok | noop
    action: str
    key: str = ""
    delta: int = 0
    chat: int = 0  # id групи: панель живе в особистих адміна


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


# ---------- налаштування чату (в особистих адміна) ----------

def _back_to_settings(chat: int, to: str = "home") -> list:
    return [btn(texts.BACK, SetCb(action=to, chat=chat), emo="back")]


def settings_home(chat: int) -> InlineKeyboardMarkup:
    grid = [btn(label, SetCb(action=key, chat=chat), emo=emo) for key, emo, label in texts.SETTINGS_MODULES]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(grid, 2),
        [btn(texts.SETTINGS_CUSTOM_BTN, SetCb(action="custom", chat=chat), emo="tools", style=SUCCESS)],
        [btn(texts.SETTINGS_REFRESH, SetCb(action="refresh", chat=chat), emo="refresh", style=PRIMARY)],
    ])


def settings_custom(chat: int) -> InlineKeyboardMarkup:
    """Кастомні налаштування: усе додаткове понад базові модулі."""
    grid = [btn(label, SetCb(action=key, chat=chat), emo=emo) for key, emo, label in texts.SETTINGS_CUSTOM_MODULES]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(grid, 2),
        [btn(texts.ROLES_CREATE, RoleCb(action="new", value=str(chat)), emo="sparkle", style=SUCCESS),
         btn(texts.ROLES_MINE, RoleCb(action="list", value=str(chat)), emo="theater")],
        [btn(texts.SETTINGS_RESET_BTN, SetCb(action="reset", chat=chat), emo="skip", style=DANGER)],
        _back_to_settings(chat),
    ])


def settings_chats(chats: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(title, SetCb(action="home", chat=chat_id), emo="people")] for chat_id, title in chats
    ])


def settings_open_pm(url: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn(label, url=url, emo="settings", style=PRIMARY)]])


def _stepper(chat: int, action: str, key: str, step: int, label: str, emo: str) -> list:
    return [
        btn("−", SetCb(action=action, key=key, delta=-step, chat=chat)),
        btn(label, SetCb(action="noop", chat=chat), emo=emo),
        btn("+", SetCb(action=action, key=key, delta=step, chat=chat)),
    ]


def _toggles(s: GroupSettings, keys: tuple[str, ...]) -> list[list]:
    result = []
    for key in keys:
        on = bool(getattr(s, key))
        emo, label = texts.TOGGLE_LABELS[key][int(on)]
        result.append([btn(label, SetCb(action="toggle", key=key, chat=s.chat_id), emo=emo,
                           style=SUCCESS if on else None)])
    return result


def settings_timers(s: GroupSettings) -> InlineKeyboardMarkup:
    keyboard = [
        _stepper(s.chat_id, "timer", key, TIMER_LIMITS[key][2],
                 f"{label}: {texts.fmt_seconds(getattr(s, key))}", emo)
        for key, (emo, label) in texts.TIMER_NAMES.items()
    ]
    keyboard.append(_back_to_settings(s.chat_id))
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def settings_lobby(s: GroupSettings) -> InlineKeyboardMarkup:
    emo, label = texts.REG_TIMER
    return InlineKeyboardMarkup(inline_keyboard=[
        _stepper(s.chat_id, "timer", "reg_time", TIMER_LIMITS["reg_time"][2],
                 f"{label}: {texts.fmt_seconds(s.reg_time)}", emo),
        *_toggles(s, ("pin_lobby", "start_admins_only")),
        _back_to_settings(s.chat_id, "custom"),
    ])


def settings_family(s: GroupSettings) -> InlineKeyboardMarkup:
    ratios = [
        btn(label, SetCb(action="ratio", key=key, chat=s.chat_id), emo=emo,
            style=SUCCESS if s.mafia_ratio == key else None)
        for key, (emo, label) in texts.RATIO_LABELS.items()
    ]
    steppers = [
        _stepper(s.chat_id, "players", key, PLAYER_LIMITS[key][2], f"{label}: {getattr(s, key)}", emo)
        for key, (emo, label) in texts.PLAYER_LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[ratios, *steppers, _back_to_settings(s.chat_id, "custom")])


def settings_roles(s: GroupSettings, custom: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        btn(f"{r.name} ({r.min_players}+)", SetCb(action="role", key=r.key, chat=s.chat_id), emo=r.key,
            style=DANGER if r.key in s.disabled_roles else SUCCESS)
        for r in ROLES.values() if r.optional and not r.custom
    ]
    buttons += [
        btn(f"{c['emoji']}{c['name']} ({c['min_players']}+)", SetCb(action="crole", key=str(c["id"]), chat=s.chat_id),
            style=SUCCESS if c["enabled"] else DANGER)
        for c in custom
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(buttons, 2),
        [btn(texts.ROLES_CREATE, RoleCb(action="new", value=str(s.chat_id)), emo="sparkle", style=PRIMARY),
         btn(texts.ROLES_MINE, RoleCb(action="list", value=str(s.chat_id)), emo="theater")],
        _back_to_settings(s.chat_id),
    ])


def settings_items(s: GroupSettings) -> InlineKeyboardMarkup:
    items = [
        btn(item.name, SetCb(action="item", key=key, chat=s.chat_id), emo=key,
            style=DANGER if key in s.disabled_items else SUCCESS)
        for key, item in ITEMS.items()
    ] if s.items_enabled else []
    return InlineKeyboardMarkup(inline_keyboard=[
        *_toggles(s, ("items_enabled",)), *rows(items, 2), _back_to_settings(s.chat_id),
    ])


def settings_toggles(s: GroupSettings, keys: tuple[str, ...], back: str = "home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[*_toggles(s, keys), _back_to_settings(s.chat_id, back)])


def settings_reset(chat: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        btn(texts.RESET_YES, SetCb(action="reset_ok", chat=chat), emo="ok", style=DANGER),
        btn(texts.BACK, SetCb(action="custom", chat=chat), emo="back"),
    ]])


# ---------- майстер власних ролей (особисті) ----------

class RoleCb(CallbackData, prefix="role"):
    # team | ability | min | save | cancel | view | toggle | delete | list
    action: str
    value: str = ""


def role_choice(action: str, options: list[tuple[str, str, str]], width: int = 2) -> InlineKeyboardMarkup:
    """options: (значення, емодзі-ключ або "", підпис)."""
    buttons = [btn(label, RoleCb(action=action, value=value), emo=emo or None) for value, emo, label in options]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(buttons, width),
        [btn(texts.ROLE_CANCEL, RoleCb(action="cancel"), emo="no")],
    ])


def role_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        btn(texts.ROLE_SAVE, RoleCb(action="save"), emo="ok", style=SUCCESS),
        btn(texts.ROLE_CANCEL, RoleCb(action="cancel"), emo="no", style=DANGER),
    ]])


def roles_list(custom: list[dict], chat: int) -> InlineKeyboardMarkup:
    buttons = [
        btn(f"{c['emoji']}{c['name']}", RoleCb(action="view", value=str(c["id"])),
            style=SUCCESS if c["enabled"] else DANGER)
        for c in custom
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(buttons, 2),
        [btn(texts.ROLES_CREATE, RoleCb(action="new", value=str(chat)), emo="sparkle", style=SUCCESS)],
        _back_to_settings(chat, "custom"),
    ])


def role_done(chat: int) -> InlineKeyboardMarkup:
    """Після збереження / скасування майстра."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(texts.ROLES_MINE, RoleCb(action="list", value=str(chat)), emo="theater"),
         btn(texts.ROLES_CREATE, RoleCb(action="new", value=str(chat)), emo="sparkle")],
        _back_to_settings(chat, "custom"),
    ])


def role_manage(role: dict) -> InlineKeyboardMarkup:
    rid = str(role["id"])
    toggle = texts.ROLE_DISABLE if role["enabled"] else texts.ROLE_ENABLE
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(toggle, RoleCb(action="toggle", value=rid), emo="refresh"),
         btn(texts.ROLE_DELETE, RoleCb(action="delete", value=rid), emo="no", style=DANGER)],
        [btn(texts.BACK, RoleCb(action="list", value=str(role["chat_id"])), emo="back")],
    ])




# ---------- кабінет Дона (власник) ----------

class OwnCb(CallbackData, prefix="own"):
    # home | player | card | give | vip | block | bc | bc_go | promos | promo_new | promo_del | buys | refund
    # | refund_go | games | stop | stop_go | design
    action: str
    value: str = ""


def _owner_back(action: str = "home") -> list:
    return [btn(texts.BACK, OwnCb(action=action), emo="back")]


def owner_home() -> InlineKeyboardMarkup:
    grid = [btn(label, OwnCb(action=key), emo=emo) for key, emo, label in texts.OWNER_MODULES]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(grid, 2),
        [btn(texts.OWNER_REFRESH, OwnCb(action="home"), emo="refresh", style=PRIMARY)],
    ])


def owner_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_owner_back()])


def owner_player(user_id: int, blocked: bool) -> InlineKeyboardMarkup:
    uid = str(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("+100", OwnCb(action="give", value=f"{uid}.shagy.100"), emo="shagy", style=SUCCESS),
         btn("+1000", OwnCb(action="give", value=f"{uid}.shagy.1000"), emo="shagy", style=SUCCESS),
         btn("−100", OwnCb(action="give", value=f"{uid}.shagy.-100"), emo="shagy", style=DANGER)],
        [btn("+10", OwnCb(action="give", value=f"{uid}.cherv.10"), emo="cherv", style=SUCCESS),
         btn("−10", OwnCb(action="give", value=f"{uid}.cherv.-10"), emo="cherv", style=DANGER),
         btn("VIP +30", OwnCb(action="vip", value=f"{uid}.30"), emo="vip", style=PRIMARY)],
        [btn(texts.OWNER_UNBLOCK if blocked else texts.OWNER_BLOCK, OwnCb(action="block", value=uid),
             emo="ok" if blocked else "lock", style=SUCCESS if blocked else DANGER)],
        [btn(texts.OWNER_OTHER_PLAYER, OwnCb(action="player"), emo="profile"), *_owner_back()],
    ])


def owner_confirm(go_label: str, go: OwnCb, back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        btn(go_label, go, emo="ok", style=DANGER),
        btn(texts.ROLE_CANCEL, OwnCb(action=back), emo="no"),
    ]])


def owner_promos(codes: list[str]) -> InlineKeyboardMarkup:
    delete = [btn(code, OwnCb(action="promo_del", value=code), emo="no") for code in codes
              if ":" not in code and len(OwnCb(action="promo_del", value=code).pack()) <= 64]
    return InlineKeyboardMarkup(inline_keyboard=[
        *rows(delete, 3),
        [btn(texts.OWNER_PROMO_NEW, OwnCb(action="promo_new"), emo="sparkle", style=SUCCESS)],
        _owner_back(),
    ])


def owner_buys(refundable: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons = [btn(label, OwnCb(action="refund", value=str(pid)), emo="star") for pid, label in refundable]
    return InlineKeyboardMarkup(inline_keyboard=[*rows(buttons, 2), _owner_back()])


def owner_games(games: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons = [btn(title, OwnCb(action="stop", value=str(chat_id)), emo="skip") for chat_id, title in games]
    return InlineKeyboardMarkup(inline_keyboard=[*rows(buttons, 1), _owner_back()])
