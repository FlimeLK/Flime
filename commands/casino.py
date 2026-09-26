# -*- coding: utf-8 -*-
"""
Казино «У Лева»: міні-режим між іграми.
Ставте ліри на події в наступній грі; коефіцієнт виграшу залежить від події (×2/×3/×5).
Події: перемога мафії, перемога мирних, Комісара усунуто до 3-го дня,
перемога третьої сторони (маніяк/заражений/диявол/самогубець).
"""

from aiogram import Bot, Router, F
import time
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType
from database.database import (
    cursor, conn,
    get_balance_async, deduct_balance_async, add_balance_to_user_async,
    casino_create_round_async, casino_get_open_round_async, casino_get_pending_round_async,
    casino_is_round_open_async, casino_place_bet_async, casino_get_bets_for_round_async,
    casino_resolve_round_async, casino_set_round_message_id_async,
    get_active_founder_ids_async, run_db_call_async,
)
from premium_emoji import emoji_to_premium
from commands import vip as vip_mod

router_casino = Router()

# Анти-дубль для багаторазових тапів по callback-кнопках.
_casino_bet_locks: dict[tuple[int, int], bool] = {}
_casino_open_dm_cooldown: dict[tuple[int, int], float] = {}

CASINO_EVENTS = [
    # (event_id, підпис, коефіцієнт виграшу). Коефіцієнт підібрано під імовірність події:
    # майже рівні (≈50/50) події — x2; рідші — більший множник.
    ("mafia_wins", "🎩 Перемога мафії", 2),
    ("civilians_win", "🤝 Перемога мирних", 2),
    ("commissioner_executed_by_day3", "🕵️ Комісара усунуто до 3-го дня", 3),
    ("third_party_win", "🃏 Перемога третьої сторони", 5),
]

BET_AMOUNTS = [5, 10, 25, 50, 100]


def _db_fetchone_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute_commit_sync(query: str, params: tuple = ()) -> None:
    cursor.execute(query, params)
    conn.commit()


async def _db_fetchone_async(query: str, params: tuple = ()):
    return await run_db_call_async(lambda: _db_fetchone_sync(query, params))


async def _db_fetchall_async(query: str, params: tuple = ()):
    return await run_db_call_async(lambda: _db_fetchall_sync(query, params))


async def _db_execute_commit_async(query: str, params: tuple = ()) -> None:
    await run_db_call_async(lambda: _db_execute_commit_sync(query, params))


def _build_casino_keyboard(round_id: int, ask_dm: bool = False):
    """У групі (ask_dm=True) - тільки кнопка «Так». В Пп (ask_dm=False) - кнопки подій для ставок."""
    builder = InlineKeyboardBuilder()
    if ask_dm:
        builder.button(text="Зробити ставку", callback_data=f"casino_open_dm:{round_id}")
    else:
        for event_id, label, odds in CASINO_EVENTS:
            builder.button(
                text=f"{label} ×{odds}",
                callback_data=f"casino_ev:{round_id}:{event_id}",
            )
    builder.adjust(1)
    return builder.as_markup()


def _build_amount_keyboard(round_id: int, event_id: str):
    """Клавіатура вибору суми ставки."""
    builder = InlineKeyboardBuilder()
    for amount in BET_AMOUNTS:
        builder.button(
            text=f"{amount} 💵",
            callback_data=f"casino_bet:{round_id}:{event_id}:{amount}",
        )
    builder.button(text="Скасувати", callback_data=f"casino_cancel:{round_id}")
    builder.adjust(2)
    return builder.as_markup()


@router_casino.message(Command("test_casino"))
async def cmd_test_casino(message: Message, bot: Bot):
    """Тестова команда для засновника: відкрити казино в поточному чаті без гри."""
    founder_ids = await get_active_founder_ids_async()
    if not message.from_user or message.from_user.id not in founder_ids:
        await message.answer("Команда тільки для засновників бота.")
        return
    chat_id = message.chat.id if message.chat else 0
    if message.chat and message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.answer("Казино тестують у групі. Напиши /test_casino в групі, де грає бот.")
        return
    round_id = await casino_create_round_async(chat_id)
    await send_casino_message(bot, chat_id, round_id)
    await message.answer("Повідомлення казино «У Лева» надіслано.", parse_mode="html")


def _casino_message_text(in_group: bool = False):
    """Текст повідомлення казино. У групі - з питанням про Пп."""
    base = (
        "🎰<b>Казино «У Лева»</b>\n\n"
        "Ставте ліри на події в <b>наступній</b> грі.\n"
        "Коефіцієнт виграшу залежить від події (вказано на кнопці: ×2, ×3, ×5).\n\n"
    )
    if in_group:
        base += ""
    return base


async def send_casino_message(bot: Bot, chat_id: int, round_id: int, in_group: bool = True):
    """
    Надіслати повідомлення казино з кнопками ставок.
    in_group=True: у групі, з питанням «Чи хочете поставити в Пп?» та кнопкою «Так».
    in_group=False: в Пп, без цієї кнопки.
    """
    text = emoji_to_premium(_casino_message_text(in_group=in_group))
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=_build_casino_keyboard(round_id, ask_dm=in_group),
        parse_mode="html",
    )
    if in_group and msg and getattr(msg, "message_id", None):
        await casino_set_round_message_id_async(round_id, msg.message_id)


async def resolve_casino_after_game(bot: Bot, chat_id: int, state, winner: str) -> int:
    """
    Після закінчення гри: вирішити раунд ставок для цієї гри (якщо є), виплатити виграші.
    Новий раунд створюється на /play, тому тут нічого не відкриваємо.
    """
    # Якщо з якихось причин залишилось кілька pending-раундів (resolved_at IS NULL),
    # резолвимо всі - щоб точно не “загубити” ставки.
    def _fetch_pending_ids():
        rows = _db_fetchall_sync(
            "SELECT id FROM casino_rounds WHERE chat_id = %s AND resolved_at IS NULL ORDER BY id ASC",
            (chat_id,),
        )
        return [r[0] for r in (rows or []) if r and r[0]]
    pending_ids = await run_db_call_async(_fetch_pending_ids)
    if not pending_ids:
        # Діагностика: немає раунду для резолву
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=emoji_to_premium("🎲 <b>Казино «У Лева»:</b> немає активного раунду для підбиття підсумків (pending=0)."),
                parse_mode="html",
            )
        except Exception:
            pass
        return 0

    first_night = getattr(state, "first_night_any_death", False) if state else False
    comm_day3 = bool(getattr(state, "commissioner_lynched_on_day", 0) and getattr(state, "commissioner_lynched_on_day", 0) <= 3) if state else False
    mafia_wins = winner == "mafia" if winner else False
    civilians_win = winner == "civilians" if winner else False
    # Третя сторона: маніяк / заражений / диявол / самогубець.
    third_party_win = winner in ("maniac", "infected", "devil", "suicide") if winner else False

    # Додаткові події + індивідуальні коефіцієнти (з CASINO_EVENTS).
    extra_outcomes = {
        "civilians_win": civilians_win,
        "third_party_win": third_party_win,
    }
    odds_by_event = {eid: odds for eid, _lbl, odds in CASINO_EVENTS}

    total_rows = 0
    total_winners = 0
    # Вважаємо «поточним» останній pending-раунд (найновіший для цієї гри)
    latest_round_id = pending_ids[-1]
    for round_id in pending_ids:
        await casino_resolve_round_async(round_id, first_night, comm_day3, mafia_wins, extra_outcomes, odds_by_event)

        def _fetch_rows():
            return _db_fetchall_sync(
                "SELECT user_id, event_id, amount, COALESCE(won, FALSE), COALESCE(payout, 0) FROM casino_bets WHERE round_id = %s",
                (round_id,),
            )
        rows = await run_db_call_async(_fetch_rows)
        if not rows:
            continue
        # У підсумковій статистиці рахуємо тільки ставки останнього (поточного) раунду,
        # але персональні повідомлення відправляємо для всіх pending-раундів.
        count_in_stats = (round_id == latest_round_id)
        if count_in_stats:
            total_rows += len(rows)
        for uid, eid, amt, won, payout in rows:
            label = next((lbl for eid2, lbl, _ in CASINO_EVENTS if eid2 == eid), str(eid))
            try:
                ur = await _db_fetchone_async("SELECT COALESCE(tg_name, '') FROM users WHERE id = %s", (int(uid),))
                win_name = (ur[0] or "").strip() or "Гравець"
                who_line = vip_mod.html_user_link(int(uid), win_name)
                if won and payout and payout > 0:
                    if count_in_stats:
                        total_winners += 1
                    text = (
                        f"{who_line}\n\n"
                        "🎲 <b>Казино «У Лева»</b>\n\n"
                        f"Ваша ставка зіграла!\n"
                        f"Подія: <b>{label}</b>\n"
                        f"Ставка: <b>{amt} 💵</b>\n"
                        f"Виграш: <b>+{payout} 💵</b>\n\n"
                        "Забирайте ліри в балансі."
                    )
                else:
                    text = (
                        f"{who_line}\n\n"
                        "🎲 <b>Казино «У Лева»</b>\n\n"
                        f"Ваша ставка не зіграла.\n"
                        f"Подія: <b>{label}</b>\n"
                        f"Ставка: <b>{amt} 💵</b>\n\n"
                        "Удачі наступного разу."
                    )
                await bot.send_message(
                    chat_id=int(uid),
                    text=emoji_to_premium(text, skip_vip_badges=True),
                    parse_mode="html",
                )
            except Exception:
                # Якщо користувач не відкривав ЛС з ботом - Telegram не дасть написати
                pass

    if total_rows:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=emoji_to_premium(f"🎲 <b>Казино «У Лева»:</b> раунд завершено. Виграшних ставок: <b>{total_winners}</b> із <b>{total_rows}</b>."),
                parse_mode="html",
            )
        except Exception:
            pass

    return 0


async def refund_casino_round(bot: Bot, chat_id: int, round_id: int) -> int:
    """
    Повертає ліри за всі ставки в раунді, якщо гра так і не почалась (таймер закінчився і гру скасовано).
    """
    # Отримуємо всі ставки для раунду
    rows = await casino_get_bets_for_round_async(round_id)
    if not rows:
        return 0

    # Повертаємо суми кожному гравцю
    refunded_total = 0
    for _bet_id, uid, _event_id, amt in rows:
        if not uid or not amt:
            continue
        await add_balance_to_user_async(int(uid), int(amt))
        refunded_total += int(amt)

    # Позначаємо раунд як завершений і закриваємо прийом ставок
    await _db_execute_commit_async(
        "UPDATE casino_rounds SET resolved_at = CURRENT_TIMESTAMP, bets_closed_at = CURRENT_TIMESTAMP WHERE id = %s",
        (round_id,),
    )

    # Інформуємо групу
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=emoji_to_premium("🎲 <b>Казино «У Лева»:</b> гра не почалась вчасно, всі ставки за цей раунд повернуто в баланс."),
            parse_mode="html",
        )
    except Exception:
        pass

    return refunded_total


@router_casino.callback_query(F.data.startswith("casino_open_dm:"))
async def casino_open_dm(callback: CallbackQuery, bot: Bot):
    """Кнопка «Так» у групі: надіслати повідомлення казино користувачу в Пп."""
    data = (callback.data or "").strip()
    parts = data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("Помилка.", show_alert=True)
        return
    try:
        round_id = int(parts[1])
    except ValueError:
        await callback.answer("Помилка.", show_alert=True)
        return
    if not await casino_is_round_open_async(round_id):
        await callback.answer("Ставки на цей раунд уже закриті.", show_alert=True)
        return
    user_id = callback.from_user.id if callback.from_user else 0
    if not user_id:
        await callback.answer("Помилка.", show_alert=True)
        return
    # Анти-спам: не відкривати одне й те саме ЛС-казино багато разів підряд.
    dm_key = (round_id, user_id)
    now_mono = time.monotonic()
    last_open = _casino_open_dm_cooldown.get(dm_key, 0.0)
    if now_mono - last_open < 2.0:
        await callback.answer("Зачекай секунду, повідомлення вже відправляється.", show_alert=False)
        return
    _casino_open_dm_cooldown[dm_key] = now_mono
    try:
        await send_casino_message(bot, user_id, round_id, in_group=False)
        await callback.answer("Вам надіслано повідомлення в особисті.", show_alert=True)
    except Exception:
        await callback.answer(
            "Не вдалося надіслати в Пп. Спробуйте спочатку написати боту в особисті /start, потім натисніть «Так» знову.",
            show_alert=True,
        )


@router_casino.callback_query(F.data.startswith("casino_ev:"))
async def casino_choose_event(callback: CallbackQuery):
    """Клік по події - показати вибір суми."""
    data = (callback.data or "").strip()
    parts = data.split(":", 2)
    if len(parts) < 3:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    _, round_id_s, event_id = parts[0], parts[1], parts[2]
    try:
        round_id = int(round_id_s)
    except ValueError:
        await callback.answer("Помилка.", show_alert=True)
        return
    # У групі перевіряємо за chat_id; у Пп - тільки за round_id з callback
    if callback.message and callback.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        open_round = await casino_get_open_round_async(callback.message.chat.id)
        if not open_round or open_round[0] != round_id:
            await callback.answer("Ставки на цей раунд уже закриті.", show_alert=True)
            return
    elif not await casino_is_round_open_async(round_id):
        await callback.answer("Ставки на цей раунд уже закриті.", show_alert=True)
        return
    label = next((lbl for eid, lbl, _ in CASINO_EVENTS if eid == event_id), event_id)
    odds = next((o for eid, _lbl, o in CASINO_EVENTS if eid == event_id), 2)
    balance = await get_balance_async(callback.from_user.id)
    await callback.message.edit_text(
        emoji_to_premium(
            f"🎲 <b>Казино «У Лева»</b>\n\n"
            f"Подія: <b>{label}</b>\n"
            f"Коефіцієнт: <b>×{odds}</b>\n"
            f"Ваш баланс: <b>{balance}</b> 💵\n\n"
            f"Оберіть суму ставки:"
        ),
        reply_markup=_build_amount_keyboard(round_id, event_id),
        parse_mode="html",
    )
    await callback.answer()


@router_casino.callback_query(F.data.startswith("casino_bet:"))
async def casino_confirm_bet(callback: CallbackQuery):
    """Підтвердити ставку: зняти гроші та записати ставку."""
    data = (callback.data or "").strip()
    parts = data.split(":")
    if len(parts) != 4:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    _, round_id_s, event_id, amount_s = parts
    try:
        round_id = int(round_id_s)
        amount = int(amount_s)
    except ValueError:
        await callback.answer("Помилка.", show_alert=True)
        return
    if amount <= 0 or amount > 10000:
        await callback.answer("Недопустима сума.", show_alert=True)
        return
    user_id = callback.from_user.id
    lock_key = (round_id, user_id)
    if _casino_bet_locks.get(lock_key):
        await callback.answer("Ставка вже обробляється, зачекай.", show_alert=True)
        return
    _casino_bet_locks[lock_key] = True
    try:
        if not await casino_is_round_open_async(round_id):
            await callback.answer("Ставки на цей раунд уже закриті.", show_alert=True)
            return
        if await get_balance_async(user_id) < amount:
            await callback.answer("Недостатньо лір. Перевір баланс у /profile.", show_alert=True)
            return
        if not await deduct_balance_async(user_id, amount):
            await callback.answer("Не вдалося списати ставку.", show_alert=True)
            return
        if not await casino_place_bet_async(round_id, user_id, event_id, amount):
            # Повертаємо гроші, якщо не вдалося записати ставку
            await add_balance_to_user_async(user_id, amount)
            await callback.answer("Ставку на цю подію ти вже зробив або ставки закриті.", show_alert=True)
            return
        label = next((lbl for eid, lbl, _ in CASINO_EVENTS if eid == event_id), event_id)
        await callback.answer(f"Ставку прийнято: {amount} 💵 на «{label}»", show_alert=False)
        nr = await _db_fetchone_async("SELECT COALESCE(tg_name, '') FROM users WHERE id = %s", (user_id,))
        nm = (nr[0] or "").strip() or (callback.from_user.first_name if callback.from_user else "Гравець")
        header = vip_mod.html_user_link(user_id, nm)
        await callback.message.edit_text(
            emoji_to_premium(
                f"{header}\n\n"
                f"Ставку <b>{amount} 💵</b> на «{label}» прийнято. Виграш при успіху: <b>{amount * 2} 💵</b>.\n\n"
                f"Чекайте результату цієї гри.",
                skip_vip_badges=True,
            ),
            parse_mode="html",
        )
    finally:
        _casino_bet_locks.pop(lock_key, None)


@router_casino.callback_query(F.data.startswith("casino_cancel:"))
async def casino_cancel(callback: CallbackQuery):
    """Повернутися до списку подій. У callback_data передано round_id для Пп."""
    await callback.answer("Скасовано.")
    round_id = None
    if callback.data and ":" in callback.data:
        try:
            round_id = int(callback.data.split(":", 1)[1])
        except ValueError:
            pass
    try:
        if callback.message and callback.message.chat:
            if round_id is not None and await casino_is_round_open_async(round_id):
                await callback.message.edit_text(
                    emoji_to_premium("🎲 <b>Казино «У Лева»</b> 🎲\n\nОберіть подію для ставки:"),
                    reply_markup=_build_casino_keyboard(round_id),
                    parse_mode="html",
                )
            elif round_id is None:
                open_round = await casino_get_open_round_async(callback.message.chat.id)
                if open_round:
                    await callback.message.edit_text(
                        emoji_to_premium("🎲 <b>Казино «У Лева»</b> 🎲\n\nОберіть подію для ставки:"),
                        reply_markup=_build_casino_keyboard(open_round[0]),
                        parse_mode="html",
                    )
    except Exception:
        pass
