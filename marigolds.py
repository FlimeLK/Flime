# -*- coding: utf-8 -*-
"""
Чорнобривці: магазин (купівля за злоті), команда подарунка, повідомлення одержувачу.
1 чорнобривця = 100 злотих.
"""
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from database.database import cursor, conn
from database.database import run_db_call_async
from commands.start import add_user_to_db, _shop_main_text_and_keyboard
from premium_emoji import emoji_to_premium

router_marigolds = Router()

MARIGOLD_EMOJI = "🌼"
PRICE_PER_ONE = 100  # злотих за 1 чорнобривцю


async def _db_fetchone(query: str, params: tuple = ()):
    def _run():
        cursor.execute(query, params)
        return cursor.fetchone()
    return await run_db_call_async(_run)


async def _db_execute_commit(query: str, params: tuple = ()) -> None:
    def _run():
        cursor.execute(query, params)
        conn.commit()
    await run_db_call_async(_run)


async def _get_balance(user_id: int) -> int:
    row = await _db_fetchone("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
    return int(row[0]) if row else 0


async def _get_marigolds(user_id: int) -> int:
    row = await _db_fetchone("SELECT COALESCE(marigolds, 0) FROM users WHERE id = %s", (user_id,))
    return int(row[0]) if row else 0


async def _ensure_user(user_id: int):
    await _db_execute_commit(
        "INSERT INTO users (id, balance, donate_coins, marigolds) VALUES (%s, 0, 0, 0) ON CONFLICT (id) DO NOTHING",
        (user_id,),
    )


async def _add_marigolds(user_id: int, count: int) -> None:
    await _ensure_user(user_id)
    await _db_execute_commit(
        "UPDATE users SET marigolds = COALESCE(marigolds, 0) + %s WHERE id = %s",
        (count, user_id),
    )


async def _deduct_marigolds(user_id: int, count: int) -> bool:
    """Повертає True, якщо вирахування виконано."""
    current = await _get_marigolds(user_id)
    if current < count:
        return False
    await _db_execute_commit(
        "UPDATE users SET marigolds = marigolds - %s WHERE id = %s",
        (count, user_id),
    )
    return True


async def _deduct_balance(user_id: int, amount: int) -> bool:
    """Повертає True, якщо вирахування виконано."""
    current = await _get_balance(user_id)
    if current < amount:
        return False
    await _db_execute_commit(
        "UPDATE users SET balance = balance - %s WHERE id = %s",
        (amount, user_id),
    )
    return True


# --- Текст у стилі бота (мафія / сім'я) ---

def _gift_notification_text(count: int) -> str:
    """Повідомлення одержувачу: хтось надіслав чорнобривці + таємнича листівка."""
    return (
        f"Хтось із сім'ї надіслав вам чорнобривці {MARIGOLD_EMOJI} ({count})… "
        f"а поряд із ними лежить таємнича листівка ❤️"
    )


# --- Магазин (купівля за злоті) ---

def _marigolds_shop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{MARIGOLD_EMOJI} 1 шт — 100 злотих", callback_data="marigolds_buy_1"),
            InlineKeyboardButton(text=f"{MARIGOLD_EMOJI} 5 шт — 500 злотих", callback_data="marigolds_buy_5"),
        ],
        [
            InlineKeyboardButton(text=f"{MARIGOLD_EMOJI} 10 шт — 1000 злотих", callback_data="marigolds_buy_10"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="marigolds_back_to_shop")],
    ])


@router_marigolds.callback_query(F.data == "marigolds_shop")
async def marigolds_shop_main(callback: CallbackQuery):
    """Головне меню чорнобривців: скільки є, купити, як дарувати."""
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в особистих повідомленнях.", show_alert=True)
        return
    user_id = callback.from_user.id
    await _ensure_user(user_id)
    balance = await _get_balance(user_id)
    count = await _get_marigolds(user_id)
    text = (
        f"🌼 <b>Чорнобривці</b> 🌼\n\n"
        f"У вас: <b>{count}</b> чорнобривців.\n"
        f"💰 Злоті: <b>{balance}</b>\n\n"
        f"1 чорнобривця = <b>{PRICE_PER_ONE}</b> злотих.\n\n"
        f"Щоб подарувати комусь: <code>/marigolds @username кількість</code>\n"
        f"або відповідь на повідомлення людини: <code>/marigolds кількість</code>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛒 Купити чорнобривці", callback_data="marigolds_shop_buy")],
        [InlineKeyboardButton(text="⬅️ Назад до крамниці", callback_data="marigolds_back_to_shop")],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="html")
    await callback.answer()


@router_marigolds.callback_query(F.data == "marigolds_shop_buy")
async def marigolds_shop_buy_menu(callback: CallbackQuery):
    """Меню купівлі: 1 / 5 / 10 шт."""
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в ЛС.", show_alert=True)
        return
    user_id = callback.from_user.id
    balance = await _get_balance(user_id)
    text = (
        f"🌼 <b>Купити чорнобривці</b>\n\n"
        f"💰 Ваш баланс: <b>{balance}</b> злотих.\n"
        f"1 чорнобривця = {PRICE_PER_ONE} злотих."
    )
    await callback.message.edit_text(text, reply_markup=_marigolds_shop_kb(), parse_mode="html")
    await callback.answer()


@router_marigolds.callback_query(F.data.startswith("marigolds_buy_"))
async def marigolds_buy_apply(callback: CallbackQuery):
    """Купівля N чорнобривців за злоті."""
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в ЛС.", show_alert=True)
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
    balance = await _get_balance(user_id)
    if balance < cost:
        await callback.answer(
            f"Недостатньо злотих. Потрібно {cost}, у вас {balance}.",
            show_alert=True,
        )
        return
    await _deduct_balance(user_id, cost)
    await _add_marigolds(user_id, n)
    new_count = await _get_marigolds(user_id)
    new_balance = await _get_balance(user_id)
    await callback.answer(f"Куплено {n} чорнобривців. У вас тепер {new_count} 🌼", show_alert=True)
    text = (
        f"🌼 <b>Чорнобривці</b> 🌼\n\n"
        f"У вас: <b>{new_count}</b> чорнобривців.\n"
        f"💰 Злоті: <b>{new_balance}</b>\n\n"
        f"1 чорнобривця = <b>{PRICE_PER_ONE}</b> злотих.\n\n"
        f"Щоб подарувати: <code>/marigolds @username кількість</code>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🛒 Купити ще", callback_data="marigolds_shop_buy")],
        [InlineKeyboardButton(text="⬅️ Назад до крамниці", callback_data="marigolds_back_to_shop")],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="html")


@router_marigolds.callback_query(F.data == "marigolds_back_to_shop")
async def marigolds_back_to_shop(callback: CallbackQuery):
    """Повернутися в головне меню крамниці (shop_main)."""
    shop_text, shop_keyboard = _shop_main_text_and_keyboard()
    await callback.message.edit_text(
        emoji_to_premium(shop_text, skip_vip_badges=False),
        reply_markup=shop_keyboard,
        parse_mode="html",
    )
    await callback.answer()


# --- Команда подарунка ---

async def _resolve_recipient(message: Message) -> Optional[int]:
    """Повертає user_id одержувача: з reply, з @username (по БД) або з числового id."""
    text = (message.text or "").strip()
    # Відповідь на повідомлення
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    parts = text.split()
    if len(parts) < 2:
        return None
    first = parts[1].strip()
    if first.startswith("@"):
        username = first[1:].lower()
        row = await _db_fetchone("SELECT id FROM users WHERE LOWER(TRIM(link)) = %s LIMIT 1", (username,))
        return int(row[0]) if row else None
    try:
        return int(first)
    except ValueError:
        return None


def _parse_gift_amount(message: Message) -> Optional[int]:
    """Повертає кількість чорнобривців з команди."""
    text = (message.text or "").strip()
    parts = text.split()
    # /marigolds [id/ @user] N  або при reply: /marigolds N
    if message.reply_to_message and len(parts) >= 2:
        try:
            return max(1, int(parts[1]))
        except ValueError:
            return None
    if len(parts) >= 3:
        try:
            return max(1, int(parts[2]))
        except ValueError:
            return None
    if len(parts) == 2:
        try:
            return max(1, int(parts[1]))
        except ValueError:
            return None
    return None


@router_marigolds.message(Command("marigolds"), F.chat.type == "private")
async def cmd_marigolds(message: Message):
    """Команда /marigolds без аргументів — показати баланс і підказку. З аргументами — подарунок."""
    await add_user_to_db(message)
    user_id = message.from_user.id
    await _ensure_user(user_id)
    text = (message.text or "").strip()
    parts = text.split()
    # Тільки /чорнобривці — показати меню
    if len(parts) == 1:
        balance = await _get_balance(user_id)
        count = await _get_marigolds(user_id)
        msg_text = (
            f"🌼 <b>Чорнобривці</b> 🌼\n\n"
            f"У вас: <b>{count}</b> чорнобривців.\n"
            f"💰 Злоті: <b>{balance}</b>\n\n"
            f"Щоб подарувати: відповідайте на повідомлення людини командою <code>/marigolds кількість</code>\n"
            f"або <code>/marigolds id_користувача кількість</code> (наприклад: /marigolds 123456789 5)"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купити чорнобривці", callback_data="marigolds_shop")],
        ])
        await message.answer(msg_text, reply_markup=keyboard, parse_mode="html")
        return

    # Подарунок
    recipient_id = await _resolve_recipient(message)
    amount = _parse_gift_amount(message)
    if recipient_id is None:
        await message.answer(
            "❌ Вкажіть одержувача: <b>відповідь на його повідомлення</b> та напишіть <code>/marigolds кількість</code>, "
            "або <code>/marigolds id_користувача кількість</code> (id можна дізнатися командою /id).",
            parse_mode="html",
        )
        return
    if amount is None or amount < 1:
        await message.answer("❌ Вкажіть кількість чорнобривців (число після одержувача).")
        return
    if recipient_id == user_id:
        await message.answer("❌ Не можна подарувати чорнобривці собі.")
        return
    if not _deduct_marigolds(user_id, amount):
        await message.answer(
            f"❌ У вас недостатньо чорнобривців. У вас: <b>{_get_marigolds(user_id)}</b>, потрібно: <b>{amount}</b>.",
            parse_mode="html",
        )
        return
    _add_marigolds(recipient_id, amount)
    # Повідомлення одержувачу в стилі скріна (таємнича листівка)
    notification = _gift_notification_text(amount)
    try:
        await message.bot.send_message(
            recipient_id,
            notification,
            parse_mode=None,
        )
    except Exception:
        pass  # якщо не вдалося надіслати в ЛС — подарунок уже перераховано
    sender_name = message.from_user.first_name or "Хтось"
    await message.answer(
        f"✅ Ви подарували <b>{amount}</b> чорнобривців {MARIGOLD_EMOJI} одержувачу. "
        f"Йому надіслано повідомлення з таємничою листівкою ❤️",
        parse_mode="html",
    )
