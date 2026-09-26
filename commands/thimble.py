# -*- coding: utf-8 -*-
"""
Міні-гра «Наперстки» — запускається, коли для повної Мафії не зібралось гравців.
Ті, хто встиг зайти в лобі, вгадують, під яким із трьох стаканців захований лимон 🍋.
Вгадав — забирає ліри 💵. Кожен гравець має рівно одну спробу; результат незалежний.
"""
import random

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from database.database import add_balance_to_user_async
from premium_emoji import emoji_to_premium

router_thimble = Router()

# Активні раунди наперстків: chat_id -> {"players": {uid: name}, "played": {uid: (cup, win_cup, reward)}}
_thimble_rounds: dict[int, dict] = {}

# Можливі виграші (ліри) за вгаданий стаканець — навмисно скромні, щоб економіка була жорсткою.
_REWARDS = [8, 10, 12, 15]


def _cups_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🥛 1", callback_data=f"thimble:{chat_id}:1"),
        InlineKeyboardButton(text="🥛 2", callback_data=f"thimble:{chat_id}:2"),
        InlineKeyboardButton(text="🥛 3", callback_data=f"thimble:{chat_id}:3"),
    ]])


def _render_board(round_: dict, *, finished: bool) -> str:
    lines = []
    for uid, name in round_["players"].items():
        res = round_["played"].get(uid)
        if res is None:
            lines.append(f"• {name} — <i>обирає…</i>")
        else:
            cup, win_cup, reward = res
            if reward > 0:
                lines.append(f"• {name} — 🍋 стаканець №{cup}, <b>+{reward} 💵</b>")
            else:
                lines.append(f"• {name} — ❌ (лимон був під №{win_cup})")
    head = "🥛 <b>НАПЕРСТКИ</b>\n\n"
    body = "\n".join(lines)
    if finished:
        tail = "\n\n<blockquote>Стаканці спорожніли. Розходимось — до наступної гри.</blockquote>"
    else:
        tail = "\n\nТисни, під яким стаканцем лимон 🍋:"
    return head + body + tail


async def start_thimble(bot, chat_id: int, players) -> bool:
    """Запустити «Наперстки» для гравців, що зайшли в лобі.
    players = [(uid, name), ...]. Повертає True, якщо гру запущено (був ≥1 гравець)."""
    cleaned: dict[int, str] = {}
    for uid, name in (players or []):
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            continue
        if uid and uid not in cleaned:
            cleaned[uid] = (str(name).strip() if name else "Гравець") or "Гравець"
    if not cleaned:
        return False

    _thimble_rounds[chat_id] = {"players": cleaned, "played": {}}
    names = ", ".join(cleaned.values())
    text = (
        "🥛 <b>НАПЕРСТКИ</b>\n\n"
        "<blockquote>Гравців для повної гри забракло — та вечір у Палермо не пропаде. "
        "Старий шахрай ховає <b>лимон</b> 🍋 під одним із трьох стаканців і спритно "
        "перемішує їх на бочці.</blockquote>\n\n"
        f"<b>За столом:</b> {names}\n\n"
        "Кожен має <b>одну</b> спробу. Вгадаєш стаканець — забираєш ліри 💵.\n"
        "Тисни, під яким стаканцем лимон 🍋:"
    )
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=emoji_to_premium(text, skip_vip_badges=True),
            reply_markup=_cups_keyboard(chat_id),
            parse_mode="html",
        )
    except Exception:
        _thimble_rounds.pop(chat_id, None)
        return False
    return True


@router_thimble.callback_query(F.data.startswith("thimble:"))
async def thimble_pick(callback: CallbackQuery):
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    try:
        chat_id = int(parts[1])
        cup = int(parts[2])
    except ValueError:
        await callback.answer("Помилка.", show_alert=True)
        return

    round_ = _thimble_rounds.get(chat_id)
    if not round_:
        await callback.answer("Ця гра вже завершена.", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id not in round_["players"]:
        await callback.answer("У наперстки грають лише ті, хто заходив у лобі.", show_alert=True)
        return
    if user_id in round_["played"]:
        await callback.answer("Ти вже зробив свій вибір.", show_alert=True)
        return

    win_cup = random.randint(1, 3)   # незалежний результат для кожного гравця
    won = (cup == win_cup)
    reward = random.choice(_REWARDS) if won else 0
    round_["played"][user_id] = (cup, win_cup, reward)

    if won:
        try:
            await add_balance_to_user_async(user_id, reward)
        except Exception:
            pass
        await callback.answer(f"🍋 Є! Лимон під стаканцем №{cup}. +{reward} 💵", show_alert=True)
    else:
        await callback.answer(f"Пусто… Лимон був під №{win_cup}. Наступного разу пощастить.", show_alert=True)

    finished = len(round_["played"]) >= len(round_["players"])
    if finished:
        _thimble_rounds.pop(chat_id, None)
    try:
        await callback.message.edit_text(
            emoji_to_premium(_render_board(round_, finished=finished), skip_vip_badges=True),
            reply_markup=None if finished else _cups_keyboard(chat_id),
            parse_mode="html",
        )
    except Exception:
        pass
