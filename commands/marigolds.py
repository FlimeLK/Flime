# -*- coding: utf-8 -*-
"""
Лимони: магазин (купівля за ліри), команда подарунка, повідомлення одержувачу.
1 лимон = 2 лір.
У магазині можна купити довільну кількість, ввівши число в чат.
"""
import html
from typing import Optional, Set

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from database.database import cursor, conn
from commands.start import add_user_to_db
from premium_emoji import emoji_to_premium, custom_emoji_id_for_symbol

router_marigolds = Router()


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_execute(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0

# Користувачі, які очікують ввести кількість для купівлі (user_id)
_waiting_marigolds_quantity: Set[int] = set()
_waiting_gift_recipient: Set[int] = set()
_waiting_gift_custom_amount: Set[int] = set()
_waiting_gift_note: Set[int] = set()
_gift_flow_state: dict[int, dict] = {}


def _is_command_message(message: Message) -> bool:
    return (getattr(message, "text", None) or "").strip().startswith("/")


def _is_waiting_marigolds_quantity(message: Message) -> bool:
    """Фільтр: обробляти текст лише якщо користувач очікує ввести кількість (щоб не перехоплювати /advent тощо)."""
    if not message.from_user or _is_command_message(message):
        return False
    return message.from_user.id in _waiting_marigolds_quantity


def _is_waiting_gift_recipient(message: Message) -> bool:
    if not message.from_user or _is_command_message(message):
        return False
    return message.from_user.id in _waiting_gift_recipient


def _is_waiting_gift_custom_amount(message: Message) -> bool:
    if not message.from_user or _is_command_message(message):
        return False
    return message.from_user.id in _waiting_gift_custom_amount


def _is_waiting_gift_note(message: Message) -> bool:
    if not message.from_user or _is_command_message(message):
        return False
    return message.from_user.id in _waiting_gift_note

MARIGOLD_EMOJI = "🍋"
PRICE_PER_ONE = 2  # лір за 1 лимон


def _marigold_icon_button(label: str, callback_data: str) -> InlineKeyboardButton:
    """Кнопка з преміум-емодзі лимони (як у крамниці / профілі)."""
    cid = custom_emoji_id_for_symbol(MARIGOLD_EMOJI)
    if cid:
        return InlineKeyboardButton(text=label, callback_data=callback_data, icon_custom_emoji_id=cid)
    return InlineKeyboardButton(text=f"{MARIGOLD_EMOJI} {label}", callback_data=callback_data)


def _get_balance(user_id: int) -> int:
    row = _db_fetchone("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
    return int(row[0]) if row else 0


def _get_marigolds(user_id: int) -> int:
    row = _db_fetchone("SELECT COALESCE(marigolds, 0) FROM users WHERE id = %s", (user_id,))
    return int(row[0]) if row else 0


def _ensure_user(user_id: int):
    _db_execute(
        "INSERT INTO users (id, balance, donate_coins, marigolds) VALUES (%s, 0, 0, 0) ON CONFLICT (id) DO NOTHING",
        (user_id,),
    )
    conn.commit()


def _add_marigolds(user_id: int, count: int) -> None:
    _ensure_user(user_id)
    _db_execute(
        "UPDATE users SET marigolds = COALESCE(marigolds, 0) + %s WHERE id = %s",
        (count, user_id),
    )
    conn.commit()


def _deduct_marigolds(user_id: int, count: int) -> bool:
    """Повертає True, якщо вирахування виконано."""
    current = _get_marigolds(user_id)
    if current < count:
        return False
    _db_execute(
        "UPDATE users SET marigolds = marigolds - %s WHERE id = %s",
        (count, user_id),
    )
    conn.commit()
    return True


def _deduct_balance(user_id: int, amount: int) -> bool:
    """Повертає True, якщо вирахування виконано."""
    current = _get_balance(user_id)
    if current < amount:
        return False
    _db_execute(
        "UPDATE users SET balance = balance - %s WHERE id = %s",
        (amount, user_id),
    )
    conn.commit()
    return True


# --- Текст у стилі бота (мафія / сім'я) ---

def _gift_notification_text(count: int, *, anonymous: bool, sender_name: str, note: str | None = None) -> str:
    note_text = (note or "").strip()
    note_block = ""
    if note_text:
        note_block = f"\n\n💌 Листівка:\n<tg-spoiler>{html.escape(note_text)}</tg-spoiler>"
    if anonymous:
        return (
            f"Хтось із сім'ї надіслав вам лимони {MARIGOLD_EMOJI} ({count})…\n"
            f"Поруч - листівка ❤️{note_block}"
        )
    safe_sender = html.escape(sender_name.strip() or "Невідомий гравець")
    return (
        f"<b>{safe_sender}</b> надіслав(ла) вам лимони {MARIGOLD_EMOJI} ({count})…\n"
        f"Поруч - листівка ❤️{note_block}"
    )


def _marigolds_word(amount: int) -> str:
    """Слово «лимони» в правильному відмінку: 1 лимон, 2-4 лимони, 5+ лимонів."""
    if amount == 1:
        return "лимон"
    if 2 <= amount <= 4:
        return "лимони"
    return "лимонів"


# --- Магазин (купівля за ліри) ---

def _marigolds_shop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _marigold_icon_button("1 шт - 2 лір", "marigolds_buy_1"),
                _marigold_icon_button("5 шт - 10 лір", "marigolds_buy_5"),
            ],
            [
                _marigold_icon_button("10 шт - 20 лір", "marigolds_buy_10"),
            ],
            [InlineKeyboardButton(text="Ввести свою кількість", callback_data="marigolds_enter_quantity")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="marigolds_back_to_shop")],
        ]
    )


@router_marigolds.callback_query(F.data == "marigolds_shop")
async def marigolds_shop_main(callback: CallbackQuery):
    """Головне меню лимонів: скільки є, купити, як дарувати."""
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в особистих повідомленнях.", show_alert=True)
        return
    user_id = callback.from_user.id
    _ensure_user(user_id)
    balance = _get_balance(user_id)
    count = _get_marigolds(user_id)
    text = (
        f"🍋 <b>Лимони</b> 🍋\n\n"
        f"У вас: <b>{count}</b> лимонів.\n"
        f"💰 Ліри: <b>{balance}</b>\n\n"
        f"1 лимон = <b>{PRICE_PER_ONE}</b> лір.\n\n"
        "Дарування лимонів: через кнопку у /profile."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛒 Купити лимони", callback_data="marigolds_shop_buy")],
        [InlineKeyboardButton(text=f"{MARIGOLD_EMOJI} Подарувати", callback_data="marigolds_gift_start")],
        [InlineKeyboardButton(text="⬅️ Назад до крамниці", callback_data="marigolds_back_to_shop")],
    ])
    await callback.message.edit_text(
        emoji_to_premium(text, skip_vip_badges=False),
        reply_markup=keyboard,
        parse_mode="html",
    )
    await callback.answer()


@router_marigolds.callback_query(F.data == "marigolds_shop_buy")
async def marigolds_shop_buy_menu(callback: CallbackQuery):
    """Меню купівлі: 1 / 5 / 10 шт або ввести свою кількість."""
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в ПП.", show_alert=True)
        return
    user_id = callback.from_user.id
    balance = _get_balance(user_id)
    text = (
        f"🍋 <b>Купити лимони</b>\n\n"
        f"💰 Ваш баланс: <b>{balance}</b> лір.\n"
        f"1 лимон = {PRICE_PER_ONE} лір.\n\n"
        f"Оберіть кількість кнопкою або натисніть «Ввести свою кількість» і напишіть число в чат."
    )
    await callback.message.edit_text(
        emoji_to_premium(text, skip_vip_badges=False),
        reply_markup=_marigolds_shop_kb(),
        parse_mode="html",
    )
    await callback.answer()


@router_marigolds.callback_query(F.data == "marigolds_enter_quantity")
async def marigolds_enter_quantity_cb(callback: CallbackQuery):
    """Запросити введення кількості в чат."""
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в ПП.", show_alert=True)
        return
    user_id = callback.from_user.id
    _waiting_marigolds_quantity.add(user_id)
    balance = _get_balance(user_id)
    max_affordable = balance // PRICE_PER_ONE if balance else 0
    text = (
        f"🍋 <b>Ввести кількість</b>\n\n"
        f"Напишіть у чат <b>число</b> - скільки лимонів купити (від 1 до 1000).\n"
        f"💰 Ваш баланс: <b>{balance}</b> лір (можна купити до {max_affordable} шт).\n\n"
        f"1 лимон = {PRICE_PER_ONE} лір."
    )
    await callback.message.edit_text(emoji_to_premium(text, skip_vip_badges=False), parse_mode="html")
    await callback.answer("Тепер напишіть число в чат.")


@router_marigolds.message(F.chat.type == "private", F.text, F.func(_is_waiting_marigolds_quantity))
async def marigolds_quantity_input(message: Message):
    """Обробка введеної кількості для купівлі (після натискання «Ввести свою кількість»)."""
    user_id = message.from_user.id
    _waiting_marigolds_quantity.discard(user_id)
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    try:
        n = int(text)
    except ValueError:
        await message.answer(
            emoji_to_premium(
                "Введіть одне число (наприклад 25). Спробуйте знову: натисніть «Купити лимони» → «Ввести свою кількість».",
                skip_vip_badges=False,
            ),
            parse_mode="html",
        )
        return
    if n < 1 or n > 1000:
        await message.answer(
            emoji_to_premium("Кількість має бути від 1 до 1000. Спробуйте знову.", skip_vip_badges=False),
            parse_mode="html",
        )
        return
    cost = n * PRICE_PER_ONE
    balance = _get_balance(user_id)
    if balance < cost:
        await message.answer(
            emoji_to_premium(
                f"Недостатньо лір. Потрібно {cost}, у вас {balance}.",
                skip_vip_badges=False,
            ),
            parse_mode="html",
        )
        return
    _deduct_balance(user_id, cost)
    _add_marigolds(user_id, n)
    new_count = _get_marigolds(user_id)
    new_balance = _get_balance(user_id)
    word = _marigolds_word(n)
    await message.answer(
        emoji_to_premium(
            f"Куплено <b>{n}</b> {word}. У вас тепер <b>{new_count}</b> лимонів 🍋, баланс: <b>{new_balance}</b> лір.",
            skip_vip_badges=False,
        ),
        parse_mode="html",
    )


@router_marigolds.callback_query(F.data.startswith("marigolds_buy_"))
async def marigolds_buy_apply(callback: CallbackQuery):
    """Купівля N лимонів за ліри."""
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в ПП.", show_alert=True)
        return
    try:
        n = int(callback.data.replace("marigolds_buy_", ""))
    except ValueError:
        await callback.answer("Помилка.", show_alert=True)
        return
    if n < 1 or n > 100:
        await callback.answer("Недійсна кількість.", show_alert=True)
        return
    user_id = callback.from_user.id
    cost = n * PRICE_PER_ONE
    balance = _get_balance(user_id)
    if balance < cost:
        await callback.answer(
            f"Недостатньо лір. Потрібно {cost}, у вас {balance}.",
            show_alert=True,
        )
        return
    _deduct_balance(user_id, cost)
    _add_marigolds(user_id, n)
    new_count = _get_marigolds(user_id)
    new_balance = _get_balance(user_id)
    await callback.answer(f"Куплено {n} лимонів. У вас тепер {new_count} 🍋", show_alert=True)
    text = (
        f"🍋 <b>Лимони</b> 🍋\n\n"
        f"У вас: <b>{new_count}</b> лимонів.\n"
        f"💰 Ліри: <b>{new_balance}</b>\n\n"
        f"1 лимон = <b>{PRICE_PER_ONE}</b> лір.\n\n"
        "Щоб подарувати: натисніть кнопку «Подарувати» у профілі."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛒 Купити ще", callback_data="marigolds_shop_buy")],
        [InlineKeyboardButton(text=f"{MARIGOLD_EMOJI} Подарувати", callback_data="marigolds_gift_start")],
        [InlineKeyboardButton(text="⬅️ Назад до крамниці", callback_data="marigolds_back_to_shop")],
    ])
    await callback.message.edit_text(
        emoji_to_premium(text, skip_vip_badges=False),
        reply_markup=keyboard,
        parse_mode="html",
    )


@router_marigolds.callback_query(F.data == "marigolds_back_to_shop")
async def marigolds_back_to_shop(callback: CallbackQuery):
    """Повернутися в головне меню крамниці (shop_main)."""
    from commands.start import _shop_main_text_and_keyboard

    shop_text, shop_keyboard = _shop_main_text_and_keyboard()
    await callback.message.edit_text(
        emoji_to_premium(shop_text, skip_vip_badges=False),
        reply_markup=shop_keyboard,
        parse_mode="html",
    )
    await callback.answer()


# --- Подарунок (тільки кнопками) ---

def _resolve_recipient_text(raw: str) -> Optional[int]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("@"):
        username = text[1:].strip().lower()
        row = _db_fetchone("SELECT id FROM users WHERE LOWER(TRIM(link)) = %s LIMIT 1", (username,))
        return int(row[0]) if row else None
    try:
        return int(text)
    except ValueError:
        return None


def _gift_amount_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data="marigolds_gift_amount:1"),
                InlineKeyboardButton(text="3", callback_data="marigolds_gift_amount:3"),
                InlineKeyboardButton(text="5", callback_data="marigolds_gift_amount:5"),
                InlineKeyboardButton(text="10", callback_data="marigolds_gift_amount:10"),
            ],
            [InlineKeyboardButton(text="Ввести свою кількість", callback_data="marigolds_gift_custom_amount")],
            [InlineKeyboardButton(text="Скасувати", callback_data="marigolds_gift_cancel")],
        ]
    )


def _gift_visibility_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Не анонімно", callback_data="marigolds_gift_visibility:named"),
                InlineKeyboardButton(text="🕶 Анонімно", callback_data="marigolds_gift_visibility:anon"),
            ],
            [InlineKeyboardButton(text="Скасувати", callback_data="marigolds_gift_cancel")],
        ]
    )


def _gift_note_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без тексту", callback_data="marigolds_gift_note_skip")],
            [InlineKeyboardButton(text="Скасувати", callback_data="marigolds_gift_cancel")],
        ]
    )


def _gift_back_kb(owner_user_id: int, target_user_id: int) -> InlineKeyboardMarkup:
    cid = custom_emoji_id_for_symbol(MARIGOLD_EMOJI)
    if cid:
        btn = InlineKeyboardButton(
            text="Подарувати взамін",
            callback_data=f"marigolds_gift_back:{owner_user_id}:{target_user_id}",
            icon_custom_emoji_id=cid,
        )
    else:
        btn = InlineKeyboardButton(
            text=f"{MARIGOLD_EMOJI} Подарувати взамін",
            callback_data=f"marigolds_gift_back:{owner_user_id}:{target_user_id}",
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn]
        ]
    )


def _clear_gift_flow(uid: int) -> None:
    _waiting_gift_recipient.discard(uid)
    _waiting_gift_custom_amount.discard(uid)
    _waiting_gift_note.discard(uid)
    _gift_flow_state.pop(uid, None)


@router_marigolds.callback_query(F.data == "marigolds_gift_start")
@router_marigolds.callback_query(F.data == "profile_marigolds_gift_start")
async def marigolds_gift_start(callback: CallbackQuery):
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в ПП.", show_alert=True)
        return
    uid = callback.from_user.id
    _ensure_user(uid)
    _clear_gift_flow(uid)
    count = _get_marigolds(uid)
    _waiting_gift_recipient.add(uid)
    await callback.message.edit_text(
        emoji_to_premium(
            "🍋 <b>Подарунок лимонів</b>\n\n"
            f"У вас: <b>{count}</b> лимонів.\n\n"
            "Надішліть у чат <b>@username</b> або <b>id</b> одержувача.\n"
            "Після цього оберете кількість і режим: анонімно чи ні.",
            skip_vip_badges=False,
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Скасувати", callback_data="marigolds_gift_cancel")]]
        ),
        parse_mode="html",
    )
    await callback.answer()


@router_marigolds.callback_query(F.data == "marigolds_gift_cancel")
async def marigolds_gift_cancel(callback: CallbackQuery):
    uid = callback.from_user.id
    _clear_gift_flow(uid)
    await marigolds_shop_main(callback)


@router_marigolds.message(F.chat.type == "private", F.text, F.func(_is_waiting_gift_recipient))
async def marigolds_gift_recipient_input(message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    recipient_id = _resolve_recipient_text(text)
    if recipient_id is None:
        await message.answer(
            emoji_to_premium(
                "Не знайшов одержувача. Надішліть коректний <code>@username</code> або <code>id</code>.",
                skip_vip_badges=False,
            ),
            parse_mode="html",
        )
        return
    if recipient_id == uid:
        await message.answer("Не можна подарувати лимони собі.")
        return
    _waiting_gift_recipient.discard(uid)
    _gift_flow_state[uid] = {"recipient_id": recipient_id}
    await message.answer(
        emoji_to_premium(
            "Оберіть кількість лимонів для подарунка:",
            skip_vip_badges=False,
        ),
        reply_markup=_gift_amount_kb(),
        parse_mode="html",
    )


@router_marigolds.callback_query(F.data.startswith("marigolds_gift_back:"))
async def marigolds_gift_back(callback: CallbackQuery):
    if not callback.from_user or not callback.message or callback.message.chat.type != "private":
        await callback.answer()
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Помилка кнопки.", show_alert=True)
        return
    try:
        owner_id = int(parts[1])
        target_id = int(parts[2])
    except Exception:
        await callback.answer("Помилка кнопки.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Ця кнопка не для вас.", show_alert=True)
        return
    uid = callback.from_user.id
    _ensure_user(uid)
    _clear_gift_flow(uid)
    if target_id == uid:
        await callback.answer("Неможливо подарувати собі.", show_alert=True)
        return
    _gift_flow_state[uid] = {
        "recipient_id": target_id,
        "force_anonymous": True,
    }
    await callback.message.answer(
        emoji_to_premium(
            "🍋 <b>Подарунок у відповідь</b>\n\n"
            "Цей подарунок буде <b>анонімним</b>, щоб не розкривати особу з попереднього анонімного подарунка.\n\n"
            "Оберіть кількість лимонів:",
            skip_vip_badges=False,
        ),
        reply_markup=_gift_amount_kb(),
        parse_mode="html",
    )
    await callback.answer()


@router_marigolds.callback_query(F.data == "marigolds_gift_custom_amount")
async def marigolds_gift_custom_amount(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in _gift_flow_state:
        await callback.answer("Спершу оберіть одержувача.", show_alert=True)
        return
    _waiting_gift_custom_amount.add(uid)
    await callback.message.edit_text(
        emoji_to_premium(
            "Введіть кількість лимонів числом (1-1000).",
            skip_vip_badges=False,
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Скасувати", callback_data="marigolds_gift_cancel")]]
        ),
        parse_mode="html",
    )
    await callback.answer()


async def _ask_visibility(message: Message, uid: int, amount: int) -> None:
    st = _gift_flow_state.get(uid)
    if not st:
        await message.answer("Сесія подарунка завершена. Почніть знову.")
        return
    st["amount"] = amount
    if bool(st.get("force_anonymous")):
        st["anonymous"] = True
        _waiting_gift_note.add(uid)
        await message.answer(
            emoji_to_premium(
                f"Кількість: <b>{amount}</b>.\n"
                "Режим: <b>анонімно</b> (фіксовано для відповіді на анонімний подарунок).\n\n"
                "Напишіть текст листівки або натисніть «Без тексту».",
                skip_vip_badges=False,
            ),
            reply_markup=_gift_note_kb(),
            parse_mode="html",
        )
        return
    await message.answer(
        emoji_to_premium(
            f"Кількість: <b>{amount}</b>.\nОберіть, як надсилати подарунок:",
            skip_vip_badges=False,
        ),
        reply_markup=_gift_visibility_kb(),
        parse_mode="html",
    )


@router_marigolds.message(F.chat.type == "private", F.text, F.func(_is_waiting_gift_custom_amount))
async def marigolds_gift_custom_amount_input(message: Message):
    uid = message.from_user.id
    _waiting_gift_custom_amount.discard(uid)
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    try:
        amount = int(text)
    except ValueError:
        await message.answer("Введіть ціле число.")
        return
    if amount < 1 or amount > 1000:
        await message.answer("Кількість має бути від 1 до 1000.")
        return
    if uid not in _gift_flow_state:
        await message.answer("Сесія подарунка завершена. Почніть знову через /profile.")
        return
    await _ask_visibility(message, uid, amount)


@router_marigolds.callback_query(F.data.startswith("marigolds_gift_amount:"))
async def marigolds_gift_amount_pick(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in _gift_flow_state:
        await callback.answer("Спершу оберіть одержувача.", show_alert=True)
        return
    try:
        amount = int((callback.data or "").split(":", 1)[1])
    except Exception:
        await callback.answer("Помилка.", show_alert=True)
        return
    if amount < 1:
        await callback.answer("Недійсна кількість.", show_alert=True)
        return
    await callback.answer()
    await _ask_visibility(callback.message, uid, amount)


@router_marigolds.callback_query(F.data.startswith("marigolds_gift_visibility:"))
async def marigolds_gift_visibility_pick(callback: CallbackQuery):
    uid = callback.from_user.id
    st = _gift_flow_state.get(uid) or {}
    recipient_id = int(st.get("recipient_id") or 0)
    amount = int(st.get("amount") or 0)
    if recipient_id <= 0 or amount <= 0:
        await callback.answer("Спершу оберіть одержувача та кількість.", show_alert=True)
        return
    is_anon = (callback.data or "").endswith(":anon")
    _gift_flow_state[uid]["anonymous"] = is_anon
    _waiting_gift_note.add(uid)
    mode_text = "анонімно" if is_anon else "не анонімно"
    await callback.message.answer(
        emoji_to_premium(
            f"Режим: <b>{mode_text}</b>.\n"
            "Напишіть текст листівки для одержувача або натисніть «Без тексту».",
            skip_vip_badges=False,
        ),
        reply_markup=_gift_note_kb(),
        parse_mode="html",
    )
    await callback.answer()


async def _finalize_gift_send(
    *,
    callback_or_message,
    sender_user,
    uid: int,
    note: str | None,
) -> None:
    st = _gift_flow_state.get(uid) or {}
    recipient_id = int(st.get("recipient_id") or 0)
    amount = int(st.get("amount") or 0)
    is_anon = bool(st.get("anonymous"))
    if recipient_id <= 0 or amount <= 0:
        _clear_gift_flow(uid)
        await callback_or_message.answer("Сесія подарунка завершена. Почніть знову.")
        return
    current = _get_marigolds(uid)
    if current < amount:
        _clear_gift_flow(uid)
        await callback_or_message.answer(
            emoji_to_premium(
                f"У вас недостатньо лимонів. У вас: <b>{current}</b>, потрібно: <b>{amount}</b>.",
                skip_vip_badges=False,
            ),
            parse_mode="html",
        )
        return
    if not _deduct_marigolds(uid, amount):
        _clear_gift_flow(uid)
        await callback_or_message.answer("Не вдалося списати лимони.")
        return
    # Зараховуємо лимони одержувачу (без цього подарунок «зникав»: списувалось з відправника, але не нараховувалось адресату).
    try:
        _add_marigolds(recipient_id, amount)
    except Exception:
        # Якщо нарахування не вдалося — повертаємо лимони відправнику, щоб не було втрат.
        try:
            _add_marigolds(uid, amount)
        except Exception:
            pass
        _clear_gift_flow(uid)
        await callback_or_message.answer("Не вдалося нарахувати лимони одержувачу. Спробуйте ще раз.")
        return
    sender_name = sender_user.full_name or sender_user.first_name or "Гравець"
    notification = _gift_notification_text(amount, anonymous=is_anon, sender_name=sender_name, note=note)
    sent = False
    reply_markup = _gift_back_kb(recipient_id, uid) if is_anon and recipient_id != uid else None
    try:
        await callback_or_message.bot.send_message(
            recipient_id,
            emoji_to_premium(notification, skip_vip_badges=False),
            parse_mode="html",
            disable_notification=True,
            reply_markup=reply_markup,
        )
        sent = True
    except Exception:
        sent = False
    word = _marigolds_word(amount)
    if sent:
        mode_text = "анонімно" if is_anon else "не анонімно"
        await callback_or_message.answer(
            emoji_to_premium(
                f"Ви подарували <b>{amount}</b> {word} {MARIGOLD_EMOJI} ({mode_text}).",
                skip_vip_badges=False,
            ),
            parse_mode="html",
        )
    else:
        await callback_or_message.answer(
            emoji_to_premium(
                f"Подарунок нараховано: <b>{amount}</b> {word} {MARIGOLD_EMOJI}.\n"
                "⚠️ Не вдалося надіслати повідомлення одержувачу в ПП.",
                skip_vip_badges=False,
            ),
            parse_mode="html",
        )
    _clear_gift_flow(uid)


@router_marigolds.callback_query(F.data == "marigolds_gift_note_skip")
async def marigolds_gift_note_skip(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in _gift_flow_state:
        await callback.answer("Сесію завершено. Почніть знову.", show_alert=True)
        return
    _waiting_gift_note.discard(uid)
    await _finalize_gift_send(
        callback_or_message=callback.message,
        sender_user=callback.from_user,
        uid=uid,
        note=None,
    )
    await callback.answer()


@router_marigolds.message(F.chat.type == "private", F.text, F.func(_is_waiting_gift_note))
async def marigolds_gift_note_input(message: Message):
    uid = message.from_user.id
    if uid not in _gift_flow_state:
        _waiting_gift_note.discard(uid)
        await message.answer("Сесію завершено. Почніть знову.")
        return
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    _waiting_gift_note.discard(uid)
    await _finalize_gift_send(
        callback_or_message=message,
        sender_user=message.from_user,
        uid=uid,
        note=text,
    )


@router_marigolds.message(Command("marigolds"), F.chat.type != "private")
async def cmd_marigolds_group(message: Message):
    """У групі - підказка, що команда тільки в ПП."""
    await message.answer(
        emoji_to_premium(
            "🍋 Команда <code>/marigolds</code> працює тільки в особистих повідомленнях з ботом.\n\n"
            "Напишіть боту в ПП і використовуйте там: /marigolds",
            skip_vip_badges=False,
        ),
        parse_mode="html",
    )


@router_marigolds.message(Command("marigolds"), F.chat.type == "private")
async def cmd_marigolds(message: Message):
    """Команда /marigolds: лише баланс/магазин. Дарування - тільки кнопками у /profile."""
    await add_user_to_db(message)
    user_id = message.from_user.id
    _ensure_user(user_id)
    text = (message.text or "").strip()
    parts = text.split()
    # Тільки /лимони - показати меню
    if len(parts) == 1:
        balance = _get_balance(user_id)
        count = _get_marigolds(user_id)
        msg_text = (
            f"🍋 <b>Лимони</b> 🍋\n\n"
            f"У вас: <b>{count}</b> лимонів.\n"
            f"💰 Ліри: <b>{balance}</b>\n\n"
            "Дарування лимонів доступне тільки кнопками у <code>/profile</code>."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купити лимони", callback_data="marigolds_shop")],
            [InlineKeyboardButton(text=f"{MARIGOLD_EMOJI} Подарувати", callback_data="marigolds_gift_start")],
        ])
        await message.answer(
            emoji_to_premium(msg_text, skip_vip_badges=False),
            reply_markup=keyboard,
            parse_mode="html",
        )
        return
    await message.answer(
        emoji_to_premium(
            "Дарування через текстову команду вимкнено.\n"
            "Використайте <code>/profile</code> -> кнопку «Подарувати лимони».",
            skip_vip_badges=False,
        ),
        parse_mode="html",
    )
