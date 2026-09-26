import sys
import os
import math
import html
import secrets
import time
from urllib.parse import urlencode
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.database import *
from database.database import (
    block_user_async, unblock_user_async, is_user_blocked_async,
    try_grant_starter_gift_async, add_gold_to_subscription_fund, get_subscription_fund_gold, deduct_user_gold_async,
    add_gold_to_user_async, get_group_creator_id_async, run_db_call_async,
)
from commands.story_achievements import ensure_achievements_sync, cmd_achievements
from commands import vip as vip_mod
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest
from premium_emoji import (
    build_emoji_callback_button,
    custom_emoji_id_for_symbol,
    emoji_to_premium,
)


router_start = Router()

# ID головного власника бота (завжди має права власника)
BOT_OWNER_ID = 1859870653
MONOBANK_JAR_URL = "https://send.monobank.ua/jar/8VRps2FLfX"
_awaiting_exchange_amount_user_ids: set[int] = set()
_awaiting_sell_buff_amount_by_user: dict[int, tuple[int, str]] = {}
_pending_pay_confirm_by_user: dict[int, dict] = {}

keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ Додати бота до групи", url='https://t.me/sicilian_mafia_bot?startgroup=true')]
])


async def _db_fetchone(query: str, params: tuple = ()):
    def _run():
        cursor.execute(query, params)
        return cursor.fetchone()
    return await run_db_call_async(_run)


async def _db_fetchall(query: str, params: tuple = ()):
    def _run():
        cursor.execute(query, params)
        return cursor.fetchall()
    return await run_db_call_async(_run)


async def _db_execute_commit(query: str, params: tuple = ()) -> None:
    def _run():
        cursor.execute(query, params)
        conn.commit()
    await run_db_call_async(_run)


async def _transfer_balance_with_fee_async(
    sender_id: int,
    receiver_id: int,
    debit_amount: int,
    credit_amount: int,
) -> tuple[bool, str]:
    """
    Атомарний переказ лір.
    debit_amount - скільки списати з відправника.
    credit_amount - скільки зарахувати отримувачу.
    Повертає: (ok, reason), де reason: insufficient_funds | receiver_not_found | db_error | ok
    """

    def _run():
        try:
            # Перевіряємо, що одержувач існує
            cursor.execute("SELECT 1 FROM users WHERE id = %s", (receiver_id,))
            if not cursor.fetchone():
                conn.rollback()
                return False, "receiver_not_found"

            # Списуємо з відправника суму + комісію (лише якщо вистачає коштів)
            cursor.execute(
                "UPDATE users SET balance = COALESCE(balance, 0) - %s "
                "WHERE id = %s AND COALESCE(balance, 0) >= %s",
                (debit_amount, sender_id, debit_amount),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return False, "insufficient_funds"

            # Зараховуємо одержувачу суму без комісії
            cursor.execute(
                "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s",
                (credit_amount, receiver_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return False, "receiver_not_found"

            conn.commit()
            return True, "ok"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, "db_error"

    return await run_db_call_async(_run)


def _db_fetchone_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_execute_sync(query: str, params: tuple = ()) -> None:
    cursor.execute(query, params)


def _build_monobank_donate_url_for_user(user_id: int) -> str:
    """
    Формує персональне посилання на банку з автопідстановкою ID в коментар.
    Використовує кілька сумісних ключів, щоб Mono підхопив значення у формі.
    """
    comment_value = str(int(user_id))
    qs = urlencode(
        {
            "comment": comment_value,
            "t": comment_value,
        }
    )
    return f"{MONOBANK_JAR_URL}?{qs}"


async def add_user_to_db(message: Message) -> bool:
    """Add or update user in database. Returns True only for newly created users."""
    username = message.from_user.username
    telegram_id = message.from_user.id
    username_telegram = message.from_user.first_name
    record = await _db_fetchone("SELECT * FROM users WHERE id = %s", (telegram_id,))
    created_new = False

    if message.chat.type == "private" or message.chat.type == "supergroup" or message.chat.type == "group":
        if record is None:
                await _db_execute_commit(
                    "INSERT INTO users (id, tg_name, link, registered_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                    (telegram_id, username_telegram, username),
                )
                created_new = True
        else:
            if record[1] != username_telegram or record[1] != username:
                await _db_execute_commit(
                    "UPDATE users SET tg_name = %s, link = %s WHERE id = %s",
                    (username_telegram, username, telegram_id,),
                )
    return created_new


async def grant_welcome_bonus_if_needed(message: Message, *, only_new_user: bool = False) -> bool:
    """Одноразово нарахувати привітальний бонус користувачу. Повертає True, якщо бонус видано."""
    if not message.from_user:
        return False
    try:
        is_new_user = await add_user_to_db(message=message)
        if only_new_user and not is_new_user:
            return False
        granted = await try_grant_starter_gift_async(message.from_user.id)
        if not granted:
            return False
        gift_text = (
            "<b>Ласкаво просимо у світ, политий соком лимонів та кров'ю зрадників.</b>\n"
            "Ти новачок у Сім'ї, і щоб тебе не прибрали в перший же день - "
            "прийми від нас (не)скромний подарунок. Повір, він тобі знадобиться 🖤\n\n"
            "<b>Начислення:</b>\n"
            "💰 2000 лір;\n"
            "🪙 10 золотих монет."
        )
        await message.answer(gift_text, parse_mode="html")
        return True
    except Exception:
        return False

@router_start.message(CommandStart())
async def start_cmd(message: Message):
    """Start command handler"""
    await add_user_to_db(message=message)
    if message.chat.type == "private":
        # Deep link «Поставити ставку в ПП»: /start casino_<group_chat_id>
        if message.text and "casino_" in message.text:
            parts = (message.text or "").strip().split(maxsplit=1)
            param = (parts[1] or "").strip() if len(parts) > 1 else ""
            if param.startswith("casino_"):
                try:
                    group_chat_id = int(param[7:].strip())
                except ValueError:
                    group_chat_id = None
                if group_chat_id is not None and message.from_user:
                    from database.database import casino_get_open_round
                    from commands.casino import send_casino_message
                    open_round = casino_get_open_round(group_chat_id)
                    if open_round:
                        await send_casino_message(message.bot, message.from_user.id, open_round[0], in_group=False)
                        return
        from commands.support import support_awaiting_description
        from commands.buy import refund_awaiting_user_ids
        if message.from_user:
            support_awaiting_description.pop(message.from_user.id, None)
            refund_awaiting_user_ids.discard(message.from_user.id)
        text = (
            "🎩 <b>СИЦИЛІЙСЬКА МАФІЯ</b> 🍋\n\n"
            "<blockquote>Палермо, 1930-ті. Тут закон пишуть не судді, а <b>Дон</b>.\n"
            "Удень усі всміхаються одне одному, а вночі хтось зникає назавжди.</blockquote>\n\n"
            "Твоя гра проста: <b>вижити</b>, вирахувати мафію — або самому <b>стати нею</b>.\n\n"
            "🎮 <b>Як почати</b>\n"
            "Додай бота в групу й напиши <code>/play</code>\n\n"
            "🕵️ Ролі · 🌙 нічні вбивства · 🗳 голосування · 🎁 бафи\n"
            "<i>Усе вирішує Сім'я.</i>"
        )
        keyboard_main = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📜 Про гру", callback_data="start_lore")],
        ])
        await message.answer(text, reply_markup=keyboard_main, parse_mode="html")
        # Щоденні ліри VIP / VIP+ - окремим повідомленням (не в тексті профілю)
        if message.from_user:
            try:
                vb, tier_v = vip_mod.vip_try_daily_currency_bonus_with_tier(message.from_user.id)
                if vb > 0 and tier_v:
                    await message.answer(
                        emoji_to_premium(
                            vip_mod.vip_daily_bonus_notification_html(vb, tier_v)
                        ),
                        parse_mode="html",
                    )
            except Exception:
                pass
        # Одноразовий привітальний бонус новому гравцю.
        await grant_welcome_bonus_if_needed(message, only_new_user=True)
    else:
        text = (
            "🎮 <b>Mafia All Capone Bot</b> 🎮\n\n"
            "💡 Додай бота до групи та пиши <code>/play</code>, щоб почати гру!"
        )
        await message.answer(text, reply_markup=keyboard, parse_mode="html")


@router_start.message(Command("block"), F.chat.type == "private")
async def cmd_block_user(message: Message):
    """Заблокувати користувача за ID (тільки для власника бота). Використання: /block 123456789"""
    if message.from_user is None or message.from_user.id != BOT_OWNER_ID:
        return
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Використання: <code>/block &lt;user_id&gt;</code>\nПриклад: /block 123456789", parse_mode="html")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("Невірний ID. Вкажіть числовий Telegram ID.")
        return
    if target_id == BOT_OWNER_ID:
        await message.answer("Не можна заблокувати власника бота.")
        return
    if await block_user_async(target_id):
        await message.answer(f"Користувача з ID <code>{target_id}</code> заблоковано. Він не зможе користуватися ботом.", parse_mode="html")
    else:
        await message.answer("Помилка при блокуванні (БД або вже заблоковано).")


@router_start.message(Command("donate_button"))
async def cmd_donate_button(message: Message):
    """
    Відправляє кнопку одразу з посиланням на Monobank банку (user_id в коментарі).
    """
    if not message.from_user:
        return
    user_id = int(message.from_user.id)
    donate_url = _build_monobank_donate_url_for_user(user_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Відкрити банку Monobank", url=donate_url)]
        ]
    )
    await message.answer(
        emoji_to_premium(
            f"💛 <b>Донат для підтримки бота</b>\n\n"
        ),
        reply_markup=kb,
        parse_mode="html",
    )


@router_start.message(Command("transfer", "pay"), F.chat.type == "private")
async def cmd_transfer_karbovantsi(message: Message):
    """
    Переказ лір: /pay <user_id|@username> <amount>
    Комісія 25% береться з суми переказу: списується amount, отримувач отримує amount*0.75.
    """
    if not message.from_user:
        return
    await add_user_to_db(message)

    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await message.answer(
            "Формат: <code>/pay &lt;id|@username&gt; &lt;кількість&gt;</code>\n"
            "Приклади:\n"
            "<code>/pay 123456789 50000</code>\n"
            "<code>/pay @username 50000</code>",
            parse_mode="html",
        )
        return

    target_raw = (parts[1] or "").strip()
    receiver_id: int | None = None
    receiver_name: str = target_raw
    if target_raw.startswith("@"):
        username = target_raw[1:].strip().lower()
        if not username:
            await message.answer("Невірний @username.")
            return
        row = await _db_fetchone(
            "SELECT id, tg_name FROM users WHERE LOWER(COALESCE(link, '')) = %s LIMIT 1",
            (username,),
        )
        if not row:
            await message.answer(
                "Користувача за цим @username не знайдено в базі.\n"
                "Нехай він спершу напише боту /start."
            )
            return
        receiver_id = int(row[0])
        receiver_name = (row[1] or target_raw).strip()
    else:
        try:
            receiver_id = int(target_raw)
        except ValueError:
            await message.answer("Вкажи валідний ID або @username.")
            return
        row = await _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (receiver_id,))
        if not row:
            await message.answer("Користувача з таким ID не знайдено в базі.")
            return
        receiver_name = (row[0] or str(receiver_id)).strip()

    try:
        amount = int(parts[2])
    except ValueError:
        await message.answer("Кількість має бути числом.")
        return

    sender_id = int(message.from_user.id)
    if receiver_id == sender_id:
        await message.answer("Не можна переказати ліри самому собі.")
        return
    if amount <= 0:
        await message.answer("Кількість має бути більшою за 0.")
        return

    sender_balance = await get_balance_async(sender_id)
    if sender_balance < amount:
        await message.answer(
            f"Недостатньо лір.\n"
            f"На балансі: <b>{sender_balance}</b>\n"
            f"Потрібно: <b>{amount}</b>",
            parse_mode="html",
        )
        return

    fee = max(1, amount - int(amount * 0.75))
    receive_amount = amount - fee
    token = secrets.token_hex(4)
    _pending_pay_confirm_by_user[sender_id] = {
        "token": token,
        "receiver_id": int(receiver_id),
        "receiver_name": receiver_name,
        "amount": amount,
        "fee": fee,
        "receive_amount": receive_amount,
        "created_at": int(time.time()),
    }
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Погодитись", callback_data=f"pay_confirm:{token}"),
                InlineKeyboardButton(text="Скасувати", callback_data=f"pay_cancel:{token}"),
            ]
        ]
    )
    await message.answer(
        f"Підтверди переказ:\n"
        f"Отримувач: <b>{html.escape(receiver_name)}</b> (<code>{receiver_id}</code>)\n"
        f"Списати з тебе: <b>{amount}</b>\n"
        f"Комісія 25%: <b>{fee}</b>\n"
        f"Отримувач отримає: <b>{receive_amount}</b>\n\n"
        f"Підтверджуєш?",
        parse_mode="html",
        reply_markup=kb,
    )


@router_start.callback_query(F.data.startswith("pay_confirm:"))
async def pay_confirm_cb(callback: CallbackQuery):
    if not callback.from_user:
        await callback.answer()
        return
    sender_id = int(callback.from_user.id)
    payload = _pending_pay_confirm_by_user.get(sender_id)
    token = (callback.data or "").split(":", 1)[1] if callback.data else ""
    if not payload or payload.get("token") != token:
        await callback.answer("Підтвердження застаріло.", show_alert=True)
        return
    if int(time.time()) - int(payload.get("created_at", 0) or 0) > 180:
        _pending_pay_confirm_by_user.pop(sender_id, None)
        await callback.answer("Час підтвердження вичерпано.", show_alert=True)
        return

    receiver_id = int(payload["receiver_id"])
    amount = int(payload["amount"])
    fee = int(payload["fee"])
    receive_amount = int(payload["receive_amount"])
    receiver_name = str(payload.get("receiver_name") or receiver_id)

    ok, reason = await _transfer_balance_with_fee_async(
        sender_id=sender_id,
        receiver_id=receiver_id,
        debit_amount=amount,
        credit_amount=receive_amount,
    )
    _pending_pay_confirm_by_user.pop(sender_id, None)
    if not ok:
        if reason == "insufficient_funds":
            await callback.answer("Недостатньо лір.", show_alert=True)
        elif reason == "receiver_not_found":
            await callback.answer("Отримувача не знайдено.", show_alert=True)
        else:
            await callback.answer("Не вдалося виконати переказ.", show_alert=True)
        try:
            if callback.message:
                await callback.message.edit_text("Переказ не виконано.")
        except Exception:
            pass
        return

    try:
        if callback.message:
            await callback.message.edit_text(
                f"Переказ виконано.\n"
                f"Отримувач: <b>{html.escape(receiver_name)}</b> (<code>{receiver_id}</code>)\n"
                f"Списано: <b>{amount}</b>\n"
                f"Комісія: <b>{fee}</b>\n"
                f"Отримувач отримав: <b>{receive_amount}</b>",
                parse_mode="html",
            )
    except Exception:
        pass
    await callback.answer("Переказ виконано.")

    try:
        sender_name = html.escape(callback.from_user.first_name or "Гравець")
        await callback.bot.send_message(
            chat_id=receiver_id,
            text=(
                f"💰 Тобі надійшов переказ лір.\n"
                f"Від: <b>{sender_name}</b>\n"
                f"Сума: <b>{receive_amount}</b>\n"
            ),
            parse_mode="html",
        )
    except Exception:
        pass


@router_start.callback_query(F.data.startswith("pay_cancel:"))
async def pay_cancel_cb(callback: CallbackQuery):
    if not callback.from_user:
        await callback.answer()
        return
    sender_id = int(callback.from_user.id)
    payload = _pending_pay_confirm_by_user.get(sender_id)
    token = (callback.data or "").split(":", 1)[1] if callback.data else ""
    if payload and payload.get("token") == token:
        _pending_pay_confirm_by_user.pop(sender_id, None)
    try:
        if callback.message:
            await callback.message.edit_text("Переказ скасовано.")
    except Exception:
        pass
    await callback.answer("Скасовано.")

# Цей handler можна залишити для callback, якщо кнопку все ж з callback_data десь викликатимуть
@router_start.callback_query(F.data == "mono_donate_open")
async def mono_donate_open_cb(callback: CallbackQuery):
    if not callback.from_user:
        await callback.answer()
        return
    user_id = int(callback.from_user.id)
    donate_url = _build_monobank_donate_url_for_user(user_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Відкрити банку Monobank", url=donate_url)]
        ]
    )
    if callback.message:
        await callback.message.answer(
            emoji_to_premium(
                f"💛 <b>Персональний донат-лінк</b>\n"
                f"ID у коментарі: <code>{user_id}</code>"
            ),
            parse_mode="html",
            reply_markup=kb,
        )
    await callback.answer()

@router_start.message(Command("unblock"), F.chat.type == "private")
async def cmd_unblock_user(message: Message):
    """Розблокувати користувача за ID (тільки для власника бота). Використання: /unblock 123456789"""
    if message.from_user is None or message.from_user.id != BOT_OWNER_ID:
        return
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Використання: <code>/unblock &lt;user_id&gt;</code>\nПриклад: /unblock 123456789", parse_mode="html")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("Невірний ID. Вкажіть числовий Telegram ID.")
        return
    if await unblock_user_async(target_id):
        await message.answer(f"Користувача з ID <code>{target_id}</code> розблоковано.", parse_mode="html")
    else:
        await message.answer("Помилка при розблокуванні або користувач не був заблокований.")


@router_start.message(
    Command("transfer_gold"),
    F.chat.type.in_(["group", "supergroup"]),
)
async def cmd_transfer_gold_to_founder(message: Message):
    """Перевести золоті монети засновнику групи. Тільки в чаті групи. Використання: /transfer_gold <кількість>"""
    if not message.from_user:
        return
    text = (message.text or "").strip().split()
    if len(text) < 2:
        await message.answer(
            "🪙 <b>Переказ золотих засновнику групи</b>\n\n"
            "Використання: <code>/transfer_gold &lt;кількість&gt;</code>\n"
            "Приклад: <code>/transfer_gold 10</code>\n\n"
            "Після підтвердження вказана кількість золотих монет буде перерахована засновнику цієї групи.",
            parse_mode="html",
        )
        return
    try:
        amount = int(text[1])
    except ValueError:
        await message.answer("Вкажіть ціле число. Приклад: <code>/transfer_gold 10</code>", parse_mode="html")
        return
    if amount < 1:
        await message.answer("Кількість має бути не менше 1.")
        return
    chat_id = message.chat.id
    creator_id = await get_group_creator_id_async(chat_id)
    if not creator_id:
        await message.answer("У цій групі немає зареєстрованого засновника (створювача групи).")
        return
    if creator_id == message.from_user.id:
        await message.answer("Ви не можете перевести золото собі.")
        return
    row = await _db_fetchone(
        "SELECT COALESCE(donate_coins, 0) FROM users WHERE id = %s",
        (message.from_user.id,),
    )
    user_gold = int(row[0]) if row else 0
    if user_gold < amount:
        await message.answer(f"Недостатньо золотих монет. У вас: {user_gold} 🪙")
        return
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Підтвердити",
                callback_data=f"transfer_founder_{message.from_user.id}_{amount}_{creator_id}_{message.message_id}",
            ),
            InlineKeyboardButton(text="Скасувати", callback_data="transfer_founder_cancel"),
        ],
    ])
    await message.answer(
        f"🪙 Перевести <b>{amount}</b> золотих монет засновнику цієї групи?\n\n"
        "Натисніть підтвердження, щоб виконати переказ.",
        reply_markup=confirm_keyboard,
        parse_mode="html",
    )


@router_start.callback_query(F.data == "transfer_founder_cancel")
async def transfer_founder_cancel_cb(callback: CallbackQuery):
    """Скасування переказу золота засновнику."""
    if not callback.message:
        return
    try:
        await callback.message.edit_text("Переказ скасовано.")
    except TelegramBadRequest:
        pass
    await callback.answer("Скасовано")


@router_start.callback_query(F.data.startswith("transfer_founder_"))
async def transfer_founder_confirm_cb(callback: CallbackQuery):
    """Підтвердження переказу золота засновнику групи."""
    if not callback.message or not callback.from_user:
        return
    data = callback.data or ""
    if data == "transfer_founder_cancel":
        return
    if not data.startswith("transfer_founder_"):
        return
    parts = data.replace("transfer_founder_", "").split("_")
    if len(parts) != 4:
        await callback.answer("Помилка формату.", show_alert=True)
        return
    try:
        user_id = int(parts[0])
        amount = int(parts[1])
        creator_id = int(parts[2])
        user_msg_id = int(parts[3])
    except ValueError:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    if callback.from_user.id != user_id:
        await callback.answer("Це підтвердження тільки для того, хто ініціював переказ.", show_alert=True)
        return
    if amount < 1:
        await callback.answer("Невірна сума.", show_alert=True)
        return
    if not await deduct_user_gold_async(user_id, amount):
        await callback.answer("Недостатньо золотих монет.", show_alert=True)
        return
    await add_gold_to_user_async(creator_id, amount)
    chat_id = callback.message.chat.id if callback.message else None
    try:
        await callback.message.delete()
    except Exception:
        pass
    if chat_id:
        try:
            await callback.bot.delete_message(chat_id=chat_id, message_id=user_msg_id)
        except Exception:
            pass
    await callback.answer("Готово ✓")


@router_start.callback_query(F.data == "start_settings_back")
async def start_settings_back_cb(callback: CallbackQuery):
    """Повернутися з налаштувань до головного меню."""
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private":
        await callback.answer()
        return
    text = (
        "🎩 <b>СИЦИЛІЙСЬКА МАФІЯ</b> 🍋\n\n"
        "<blockquote>Палермо, 1930-ті. Тут закон пишуть не судді, а <b>Дон</b>.\n"
        "Удень усі всміхаються одне одному, а вночі хтось зникає назавжди.</blockquote>\n\n"
        "Твоя гра проста: <b>вижити</b>, вирахувати мафію — або самому <b>стати нею</b>.\n\n"
        "🎮 <b>Як почати</b>\n"
        "Додай бота в групу й напиши <code>/play</code>\n\n"
        "🕵️ Ролі · 🌙 нічні вбивства · 🗳 голосування · 🎁 бафи\n"
        "<i>Усе вирішує Сім'я.</i>"
    )
    keyboard_main = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Про гру", callback_data="start_lore")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard_main, parse_mode="html")
    except TelegramBadRequest:
        pass
    await callback.answer()


# [removed] колбек start_story_yes (сюжет вимкнено)
async def start_story_yes_cb(callback: CallbackQuery):
    """Так - пояснюємо: сюжет відкривається через досягнення, через 1–3 дні прийде повідомлення."""
    if not callback.message or not callback.from_user:
        return
    if cursor is None or conn is None:
        await callback.answer("Помилка сервісу.", show_alert=True)
        return
    try:
        row = await _db_fetchone(
            "SELECT sc.id FROM story_cards sc JOIN user_story_cards usc ON usc.card_id = sc.id "
            "WHERE usc.user_id = %s AND sc.card_order = 0",
            (callback.from_user.id,),
        )
        if row:
            await callback.answer("Сюжет вже відкрито. Дивись: /story", show_alert=True)
            return
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")],
        ])
        await callback.message.edit_text(
            "📖 <b>Як відкрити сюжет</b>\n\n"
            "Грай у мафію в групах і виконуй досягнення.\n\n"
            "Прогрес по досягненнях: /achievements",
            parse_mode="html",
            reply_markup=keyboard_back,
        )
        await callback.answer()
    except Exception:
        await callback.answer("Помилка.", show_alert=True)
    return


# [removed] колбек start_story_no (сюжет вимкнено)
async def start_story_no_cb(callback: CallbackQuery):
    """Ні - коротке повідомлення."""
    if callback.message:
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")],
        ])
        await callback.message.edit_text(
            "Добре. Коли захочете - напишіть /story.",
            reply_markup=keyboard_back,
        )
    await callback.answer()


# [removed] колбек start_quest (сюжет вимкнено)
async def start_quest_cb(callback: CallbackQuery):
    """Розпочати перше завдання - питаємо «поринути» або показуємо сюжет."""
    if not callback.message or not callback.from_user:
        return
    user_id = callback.from_user.id
    if cursor and conn:
        try:
            row = await _db_fetchone(
                "SELECT sc.id FROM story_cards sc JOIN user_story_cards usc ON usc.card_id = sc.id "
                "WHERE usc.user_id = %s AND sc.card_order = 0",
                (user_id,),
            )
            if row:
                await callback.answer("Перше завдання вже розпочато. Дивись сюжет: /story", show_alert=True)
                return
            keyboard_story = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Так", callback_data="start_story_yes")],
                [InlineKeyboardButton(text="Ні", callback_data="start_story_no")],
                [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")],
            ])
            await callback.message.edit_text(
                "Чи хочете ви поринути в світ мафії?",
                reply_markup=keyboard_story,
            )
        except Exception:
            keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")],
            ])
            await callback.message.edit_text("Напиши /story, щоб переглянути сюжет.", reply_markup=keyboard_back)
    else:
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")],
        ])
        await callback.message.edit_text("Напиши /story для сюжету та завдань.", reply_markup=keyboard_back)
    await callback.answer()


# [removed] колбек start_collection (сюжетні картки вимкнено)
async def start_collection_cb(callback: CallbackQuery):
    """Моя колекція - показуємо відкриту сюжетку або підказку."""
    if not callback.message:
        return
    if cursor and conn:
        try:
            user_id = callback.from_user.id if callback.from_user else 0
            ensure_achievements_sync()  # оновлює синхронізацію і видаляє застарілі картки
            rows = _filter_obsolete_cards(await _db_fetchall(
                "SELECT sc.card_order, sc.title_uk FROM story_cards sc "
                "JOIN user_story_cards usc ON usc.card_id = sc.id WHERE usc.user_id = %s ORDER BY sc.card_order",
                (user_id,),
            ))
            
            # Клавіатура з кнопкою "Назад"
            keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")]
            ])
            
            if not rows:
                await callback.message.edit_text(
                    "🗃 <b>Моя колекція</b>\n\n"
                    "Сюжет поки не відкрито. Натисни «Розпочати перше завдання» в /start.\n\n"
                    "Напиши /story після відкриття.",
                    parse_mode="html",
                    reply_markup=keyboard_back,
                )
            else:
                lines = [f"📌 {title}" for _order, title in rows]
                await callback.message.edit_text(
                    f"🗃 <b>Моя колекція</b>\n\n" + "\n\n".join(lines) + "\n\nНапиши /story, щоб перечитати.",
                    parse_mode="html",
                    reply_markup=keyboard_back,
                )
        except Exception:
            keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")]
            ])
            await callback.message.edit_text("Напиши /story, щоб переглянути сюжет.", reply_markup=keyboard_back)
    else:
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")]
        ])
        await callback.message.edit_text("Напиши /story для сюжету.", reply_markup=keyboard_back)
    await callback.answer()


def _cleanup_unused_story_cards():
    """Legacy maintenance hook; cleanup is handled elsewhere."""
    return


LORE_TEXT = (
    "📜 <b>Про гру — Сицилійська Мафія</b>\n\n"
    "<blockquote>Сицилія, 1930-ті. Сонце випалює землю, а між лимонних гаїв тягнеться запах цитрусів, пороху й тихого страху.\n\n"
    "Тут держава далеко, а <b>Дон</b> — близько. Закон один: мовчи або зникни. Це і є <b>омерта</b>.\n\n"
    "Клани ділять порт Палермо, ринки й виноградники, і за кожну діжку лимонів хтось платить кров'ю. "
    "«Чорне золото» тут — не нафта, а цитрус, вода й страх, який тримає всіх у покорі.\n\n"
    "Удень — усмішки, міцна кава й святі образи на стінах.\n"
    "Уночі — постріл у провулку й тіло, якого ніхто «не бачив».\n\n"
    "🔫 Tommy Gun звучить голосніше за церковні дзвони.</blockquote>\n\n"
    "<i>У цьому світі немає святих.</i>\n"
    "Тут є тільки <b>Сім'я</b>, твій револьвер і місто, яке ніколи не прощає помилок."
)


@router_start.callback_query(F.data == "start_lore")
async def start_lore_cb(callback: CallbackQuery):
    """Про всесвіт гри: Галицька Мафія."""
    if not callback.message:
        return
    keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Повернутися", callback_data="start_settings_back")],
    ])
    await callback.message.edit_text(LORE_TEXT, parse_mode="html", reply_markup=keyboard_back)
    await callback.answer()


@router_start.message(Command("id"))
async def id_cmd(message: Message):
    """Show chat/user ID"""
    if message.chat.type == "private":
        await message.answer(
            f"🆔 <b>Твій Telegram ID</b> 🆔\n\n"
            f"📋 <b>ID:</b> <code>{message.chat.id}</code>\n\n"
            f"💡 <i>Використовуй цей ID для реєстрації груп та інших налаштувань.</i>",
            parse_mode="html"
        )
    if message.chat.type in ["supergroup", "group"]:
        await message.answer(
            f"🆔 <b>ID цього чату</b> 🆔\n\n"
            f"📁 <b>Назва:</b> {message.chat.title}\n"
            f"🆔 <b>ID:</b> <code>{message.chat.id}</code>\n\n"
            f"💡 <i>Використовуй цей ID для реєстрації групи в <code>/construct_event</code></i>",
            parse_mode="html"
        )


@router_start.message(Command("help"))
async def help_cmd(message: Message):
    """Help command handler"""
    from aiogram.enums import ChatMemberStatus
    
    # Перевіряємо, чи користувач є власником/адміном якоїсь групи
    is_owner = False
    is_admin = False
    
    # Головний власник бота завжди має права власника
    if message.from_user.id == BOT_OWNER_ID:
        is_owner = True
    else:
        try:
            # Перевіряємо в БД
            creator_result = await _db_fetchone(
                "SELECT creator_id FROM admin_panel WHERE creator_id = %s",
                (message.from_user.id,),
            )
            if creator_result:
                is_owner = True
            
            # Якщо це група, перевіряємо статус в Telegram
            if message.chat.type in ["supergroup", "group"]:
                try:
                    chat_member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
                    if chat_member.status == ChatMemberStatus.CREATOR:
                        is_owner = True
                    elif chat_member.status == ChatMemberStatus.ADMINISTRATOR:
                        is_admin = True
                except:
                    pass
        except:
            pass
    
    # Базові команди для всіх
    help_text = (
        "📖 <b>ДОПОМОГА</b>\n\n"
        "🎯 <b>Як грати</b>\n"
        "<blockquote>Гравці таємно діляться на <b>мирних</b> і <b>мафію</b>.\n\n"
        "🌃 <b>Уночі</b> мафія тихо прибирає одного гравця, а особливі ролі діють: лікар лікує, комісар перевіряє.\n"
        "☀️ <b>Удень</b> усі шукають зрадника й голосують, кого стратити.\n"
        "🏆 <b>Мирні</b> виграють, коли мафії не лишилось; <b>мафія</b> — коли їх стало більшість.</blockquote>\n\n"
        "🎮 <b>Основні команди</b>\n\n"
        "<code>/start</code> - Початок роботи з ботом\n"
        "<code>/play</code> - Запустити гру в Mafia\n"
        "<code>/start_game</code> - Запустити гру одразу (без очікування)\n"
        "<code>/leave</code> або <code>/leave_game</code> - Покинути гру\n"
        "<code>/carry_on</code> - Продовжити реєстрацію (додати секунди до таймера)\n"
        "<code>/shop</code> - Магазин підписок\n"
        "<code>/buff_shop</code> - Магазин бафів\n"
        "<code>/marigolds</code> - Купити лимони 🍋\n"
        "<code>/my_subscription</code> - Перевірити підписку\n"
        "<code>/id</code> - Дізнатися ID чату/користувача\n"
        "<code>/promocode</code> - Ввести промокод\n\n"
    )
    
    # Додаткові команди для власників/адмінів
    if is_owner or is_admin:
        help_text += (
            "👑 <b>Команди для власників/адміністраторів:</b>\n\n"
            "<code>/construct_event</code> - Налаштувати ролі\n"
            "<code>/set_registration_time</code> - Встановити час реєстрації для групи\n"
            "   Приклад: <code>/set_registration_time 120</code> (встановити 120 секунд)\n\n"
        )
    
    help_text += (
        "⚠️ <b>Відповідальність</b>\n"
        "<blockquote>За будь-яку інформацію, яку надіслав бот, відповідальність несе <b>власник чату</b>, якщо це не реклама.</blockquote>\n\n"
        "💡 <i>Маєш питання? Звертайся до власника чату або тех. підтримки нижче.</i>"
    )
    
    if message.chat.type == "private":
        keyboard_help = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Тех. Підтримка", callback_data="support_main")],
        ])
        await message.answer(
            emoji_to_premium(help_text, skip_vip_badges=False),
            reply_markup=keyboard_help,
            parse_mode="html",
        )
    else:
        await message.answer(emoji_to_premium(help_text, skip_vip_badges=False), parse_mode="html")


async def _get_profile_content_async(user_id: int, first_name: str = None, username: str = None):
    """Повертає (текст профілю, клавіатура) для показу профілю гравця."""
    ensure_db_connection_usable()
    result = await _db_fetchone("""
    SELECT tg_name, link, balance, COALESCE(donate_coins, 0), COALESCE(marigolds, 0), killed, cured, votes
    FROM users
    WHERE id = %s
    """, (user_id,))
    if not result:
        balance = 0
        donate_coins = 0
        marigolds = 0
        killed = 0
        cured = 0
        votes = 0
        name = first_name or username or "Гравець"
    else:
        tg_name, link, balance, donate_coins, marigolds, killed, cured, votes = result
        balance = balance if balance is not None else 0
        donate_coins = donate_coins if donate_coins is not None else 0
        marigolds = marigolds if marigolds is not None else 0
        killed = killed if killed is not None else 0
        cured = cured if cured is not None else 0
        votes = votes if votes is not None else 0
        name = tg_name or first_name or "Гравець"
    
    header = vip_mod.html_user_link(user_id, name)
    profile_text = (
        f"🎩 <b>Досьє Сім'ї</b>\n"
        f"{header}\n\n"
        "<blockquote>"
        f"💰 Ліри: <b>{balance}</b>\n"
        f"🪙 Золоті монети: <b>{donate_coins}</b>\n"
        f"🍋 Лимони: <b>{marigolds}</b>"
        "</blockquote>"
    )

    kb_rows = [
        [_icon_button("💰", "Крамниця", "shop_main")],
        [_icon_button("🎯", "Мої бафи", "buffshop_owned")],
        [_icon_button("⚒️", "VIP", "profile_subscription")],
    ]
    if vip_mod.active_vip_tier(user_id) == "vip_plus":
        kb_rows.append(
            [_icon_button("⛏️", "Значок VIP+", "vip_badge_menu")],
        )
    # Завжди остання, бо це довгий інформаційний екран.
    kb_rows.append(
        [_icon_button("📜", "Сицилія 30-х", "profile_galicia_30s")],
    )
    profile_keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    return profile_text, profile_keyboard


# Telegram інколи відхиляє повідомлення, якщо custom_emoji_id не збігається з базовим символом.
_PREMIUM_FALLBACK_SKIP = frozenset(("⛏️", "🔥"))


def _premium_html_variants(html_plain: str, *, skip_vip_badges: bool = False) -> tuple[str, ...]:
    return (
        emoji_to_premium(html_plain, skip_vip_badges=skip_vip_badges),
        emoji_to_premium(html_plain, skip_vip_badges=skip_vip_badges, skip_chars=_PREMIUM_FALLBACK_SKIP),
        html_plain,
    )


async def _answer_html_premium_fallback(
    message: Message,
    html_plain: str,
    *,
    skip_vip_badges: bool = False,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    for body in _premium_html_variants(html_plain, skip_vip_badges=skip_vip_badges):
        try:
            await message.answer(body, reply_markup=reply_markup, parse_mode="html")
            return
        except TelegramBadRequest:
            continue


async def _edit_html_premium_fallback(
    msg: Message,
    html_plain: str,
    *,
    skip_vip_badges: bool = False,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    for body in _premium_html_variants(html_plain, skip_vip_badges=skip_vip_badges):
        try:
            await msg.edit_text(body, reply_markup=reply_markup, parse_mode="html")
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            continue


def _icon_button(symbol: str, label: str, callback_data: str) -> InlineKeyboardButton:
    """Inline кнопка з premium icon_custom_emoji_id (як у /egg), з fallback на звичайний текст."""
    cid = custom_emoji_id_for_symbol(symbol)
    if cid:
        return InlineKeyboardButton(
            text=label,
            callback_data=callback_data,
            icon_custom_emoji_id=cid,
        )
    return InlineKeyboardButton(text=f"{symbol} {label}", callback_data=callback_data)


def _vip_badge_menu_text_and_keyboard(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Окреме меню вибору значка VIP+ (не змішується з головним профілем)."""
    current = vip_mod.get_vip_plus_badge_emoji(user_id)
    current_key = vip_mod.get_vip_plus_badge_choice_key(user_id)
    text = (
        "🎨 <b>Значок VIP+</b>\n\n"
        "<i>Обери емодзі - воно буде біля імені в грі та командах.</i>\n\n"
        f"Зараз обрано: {current}"
    )
    badge_map = vip_mod.get_vip_plus_badge_emoji_map(user_id)
    badge_row = []
    for key in badge_map.keys():
        sym = badge_map[key]
        cid = custom_emoji_id_for_symbol(sym)
        badge_row.append(
            build_emoji_callback_button(
                f"vip_badge:{key}",
                text=sym,
                is_selected=(key == current_key),
                icon_custom_emoji_id=cid,
            )
        )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            badge_row,
            [InlineKeyboardButton(text="Повернутися", callback_data="vip_badge_back_profile")],
        ]
    )
    return text, kb


def _shop_main_text_and_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    """Текст і клавіатура головного меню «Крамниця» (однаково в профілі / маргаритках / fallback)."""
    shop_text = (
        "💴 <b>Крамниця</b>\n\n"
        "Оберіть розділ:\n\n"
        "1. <b>Золоті монети</b> - преміальна валюта\n"
        "2. <b>Бафи</b> - тимчасові покращення для гри.\n"
        "3. <b>Лимони</b> - соковиті подарунки для близьких."
    )
    shop_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [_icon_button("🪙", "Золоті монети", "shop_section_coins")],
            [_icon_button("⚡", "Бафи", "buff_shop_menu")],
            [_icon_button("🍋", "Лимони", "marigolds_shop")],
            [InlineKeyboardButton(text="Повернутися", callback_data="buffshop_back_to_profile")],
        ]
    )
    return shop_text, shop_keyboard


@router_start.callback_query(F.data == "shop_main")
async def shop_main_cb(callback: CallbackQuery):
    """Головне меню крамниці"""
    shop_text, shop_keyboard = _shop_main_text_and_keyboard()
    await callback.message.edit_text(
        emoji_to_premium(shop_text, skip_vip_badges=False),
        reply_markup=shop_keyboard,
        parse_mode="html",
    )
    await callback.answer()

@router_start.message(Command("profile"))
async def profile_cmd(message: Message):
    """Profile command handler - show user profile with balance and Мої бафи"""
    if message.chat.type != "private":
        await message.answer(
            "👤 <b>Профіль</b> 👤\n\n"
            "💡 <i>Ця команда доступна тільки в особистих повідомленнях з ботом.</i>\n\n"
            "📩 Напиши мені: @sicilian_mafia_bot",
            parse_mode="html"
        )
        return
    await add_user_to_db(message=message)
    try:
        vb, tier_v = vip_mod.vip_try_daily_currency_bonus_with_tier(message.from_user.id)
        if vb > 0 and tier_v:
            await message.answer(
                emoji_to_premium(vip_mod.vip_daily_bonus_notification_html(vb, tier_v)),
                parse_mode="html",
            )
    except Exception:
        pass
    profile_text, profile_keyboard = await _get_profile_content_async(
        message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username
    )
    farewell = vip_mod.consume_expired_vip_farewell_message(message.from_user.id)
    if farewell:
        profile_text = f"{profile_text}\n\n{farewell}"
    await _answer_html_premium_fallback(
        message,
        profile_text,
        skip_vip_badges=False,
        reply_markup=profile_keyboard,
    )


@router_start.message(Command("balance"))
async def balance_cmd(message: Message):
    if message.chat.type != "private":
        await message.answer(
            "💰 <b>Баланс</b>\n\n<i>Команда доступна в особистих повідомленнях з ботом.</i>",
            parse_mode="html",
        )
        return
    await add_user_to_db(message=message)
    uid = message.from_user.id
    try:
        vb, tier_v = vip_mod.vip_try_daily_currency_bonus_with_tier(uid)
        if vb > 0 and tier_v:
            await message.answer(
                emoji_to_premium(vip_mod.vip_daily_bonus_notification_html(vb, tier_v)),
                parse_mode="html",
            )
    except Exception:
        pass
    row = await _db_fetchone(
        "SELECT COALESCE(balance, 0), COALESCE(NULLIF(TRIM(tg_name), ''), '') FROM users WHERE id = %s",
        (uid,),
    )
    bal = int(row[0]) if row else 0
    nm = (row[1] or message.from_user.first_name or "Гравець") if row else (message.from_user.first_name or "Гравець")
    head = vip_mod.html_user_link(uid, nm)
    text = f"{head}\n\n💰 <b>Баланс:</b> {bal} лір"
    await _answer_html_premium_fallback(message, text, skip_vip_badges=False)


@router_start.message(Command("top"))
async def top_cmd(message: Message):
    if message.chat.type != "private":
        await message.answer(
            "🏆 <b>Топ</b>\n\n<i>Команда доступна в особистих повідомленнях з ботом.</i>",
            parse_mode="html",
        )
        return
    await add_user_to_db(message=message)
    rows = await _db_fetchall(
        """
        SELECT id, COALESCE(NULLIF(TRIM(tg_name), ''), '-'), COALESCE(balance, 0)
        FROM users ORDER BY COALESCE(balance, 0) DESC LIMIT 15
        """
    )
    rows = rows or []
    lines = []
    vip_count = 0
    for i, (rid, name, val) in enumerate(rows, 1):
        if vip_mod.active_vip_tier(int(rid)):
            vip_count += 1
        plain = str(name or "-").strip() or "-"
        lines.append(f"{i}. {vip_mod.html_user_link(int(rid), plain)} - 💰 <b>{val}</b>")
    body = "\n".join(lines) if lines else "Поки порожньо."
    if vip_count >= 3:
        body += "\n\n⚒️ <i>У топі сьогодні багато тих, хто грає з VIP.</i>"
    text = "🏆 <b>Топ за лірами</b>\n\n" + body
    await _answer_html_premium_fallback(message, text, skip_vip_badges=False)


@router_start.callback_query(F.data == "vip_badge_menu")
async def vip_badge_menu_cb(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в особистих повідомленнях з ботом.", show_alert=True)
        return
    uid = callback.from_user.id
    if vip_mod.active_vip_tier(uid) != "vip_plus":
        await callback.answer("Доступно лише для VIP+.", show_alert=True)
        return
    text, kb = _vip_badge_menu_text_and_keyboard(uid)
    await _edit_html_premium_fallback(callback.message, text, skip_vip_badges=False, reply_markup=kb)
    await callback.answer()


@router_start.callback_query(F.data == "vip_badge_back_profile")
async def vip_badge_back_profile_cb(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    if callback.message.chat.type != "private":
        await callback.answer("Тільки в особистих повідомленнях з ботом.", show_alert=True)
        return
    uid = callback.from_user.id
    profile_text, profile_keyboard = await _get_profile_content_async(
        uid,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username,
    )
    farewell = vip_mod.consume_expired_vip_farewell_message(uid)
    if farewell:
        profile_text = f"{profile_text}\n\n{farewell}"
    await _edit_html_premium_fallback(
        callback.message,
        profile_text,
        skip_vip_badges=False,
        reply_markup=profile_keyboard,
    )
    await callback.answer()


@router_start.message(Command("vip_badge"))
async def vip_badge_cmd(message: Message):
    if message.chat.type != "private":
        await message.answer(
            "🎨 <b>Значок VIP+</b>\n\n<i>Команда доступна в особистих повідомленнях з ботом.</i>",
            parse_mode="html",
        )
        return
    await add_user_to_db(message=message)
    uid = message.from_user.id
    if vip_mod.active_vip_tier(uid) != "vip_plus":
        await message.answer(
            "🎨 <b>Значок VIP+</b>\n\n"
            "<i>Налаштування значка доступне лише з підпискою VIP+.</i>\n"
            "Оформити: <code>/profile</code> → Підписка.",
            parse_mode="html",
        )
        return
    text, kb = _vip_badge_menu_text_and_keyboard(uid)
    await _answer_html_premium_fallback(message, text, skip_vip_badges=False, reply_markup=kb)


@router_start.callback_query(F.data.startswith("vip_badge:"))
async def vip_badge_pick_cb(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    uid = callback.from_user.id
    parts = (callback.data or "").split(":", 1)
    key = parts[1] if len(parts) > 1 else ""
    if vip_mod.active_vip_tier(uid) != "vip_plus":
        await callback.answer("Доступно лише для VIP+.", show_alert=True)
        return
    if not vip_mod.set_vip_plus_badge_choice(uid, key):
        await callback.answer("Невідомий значок.", show_alert=True)
        return
    await callback.answer("Значок оновлено!")
    text, kb = _vip_badge_menu_text_and_keyboard(uid)
    await _edit_html_premium_fallback(callback.message, text, skip_vip_badges=False, reply_markup=kb)


@router_start.callback_query(F.data == "buffshop_back_to_profile")
async def profile_back_from_buffs(callback: CallbackQuery):
    """Повернення з «Мої бафи» на профіль."""
    if not callback.message or not callback.from_user:
        await callback.answer()
        return
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в приватному чаті.", show_alert=True)
        return
    try:
        profile_text, profile_keyboard = await _get_profile_content_async(
            callback.from_user.id,
            first_name=callback.from_user.first_name,
            username=callback.from_user.username
        )
        try:
            farewell = vip_mod.consume_expired_vip_farewell_message(callback.from_user.id)
            if farewell:
                profile_text = f"{profile_text}\n\n{farewell}"
        except Exception:
            pass
        await _edit_html_premium_fallback(
            callback.message,
            profile_text,
            skip_vip_badges=False,
            reply_markup=profile_keyboard,
        )
    except Exception as e:
        try:
            print(f"[start] buffshop_back_to_profile fallback: {e!r}")
        except Exception:
            pass
        # Fallback-реконструкція профілю, щоб кнопка «Повернутися» не зависала.
        try:
            ensure_db_connection_usable()
            uid = callback.from_user.id
            row = await _db_fetchone(
                "SELECT COALESCE(balance, 0), COALESCE(donate_coins, 0), COALESCE(marigolds, 0) FROM users WHERE id = %s",
                (uid,),
            ) or (0, 0, 0)
            balance = int(row[0] or 0)
            donate_coins = int(row[1] or 0)
            marigolds = int(row[2] or 0)
            name = callback.from_user.first_name or callback.from_user.username or "Гравець"
            header = vip_mod.html_user_link(uid, name)
            profile_text = (
                f"{header}\n\n"
                f"💰 Ліри: {balance}\n"
                f"🪙 Золоті монети: {donate_coins}\n"
                f"🍋 Лимони: {marigolds}\n"
            )
            kb_rows_fb = [
                [_icon_button("💰", "Крамниця", "shop_main")],
                [_icon_button("🎯", "Мої бафи", "buffshop_owned")],
                [_icon_button("⚒️", "VIP", "profile_subscription")],
            ]
            if vip_mod.active_vip_tier(uid) == "vip_plus":
                kb_rows_fb.append(
                    [_icon_button("⛏️", "Значок VIP+", "vip_badge_menu")],
                )
            kb_rows_fb.append(
                [_icon_button("📜", "Сицилія 30-х", "profile_galicia_30s")],
            )
            profile_keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows_fb)
            try:
                await _edit_html_premium_fallback(
                    callback.message,
                    profile_text,
                    skip_vip_badges=False,
                    reply_markup=profile_keyboard,
                )
            except Exception:
                # Якщо редагування поточного повідомлення недоступне - надсилаємо профіль новим.
                body = emoji_to_premium(profile_text, skip_vip_badges=False)
                await callback.message.answer(body, reply_markup=profile_keyboard, parse_mode="html")
        except Exception:
            await callback.answer("Не вдалося повернутись у профіль.", show_alert=True)
            return
    await callback.answer()


# [removed] колбек profile_story (сюжет вимкнено)
async def profile_story_cb(callback: CallbackQuery):
    """Відкрити меню сюжетів із профілю."""
    if not callback.message:
        await callback.answer()
        return
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        await cmd_story(callback.message)
    except Exception as e:
        try:
            print(f"[start] profile_story_cb: {e!r}")
        except Exception:
            pass
        try:
            await callback.message.answer(
                "Не вдалося відкрити сюжет. Спробуй команду /story.",
                parse_mode="html",
            )
        except Exception:
            pass


@router_start.callback_query(F.data == "profile_achievements")
async def profile_achievements_cb(callback: CallbackQuery):
    """Відкрити досягнення із профілю."""
    if not callback.message:
        await callback.answer()
        return
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        await cmd_achievements(callback.message)
    except Exception as e:
        try:
            print(f"[start] profile_achievements_cb: {e!r}")
        except Exception:
            pass
        try:
            await callback.message.answer(
                "Не вдалося відкрити досягнення. Спробуй команду /achievements.",
                parse_mode="html",
            )
        except Exception:
            pass


# [removed] колбек profile_cards (сюжетні картки вимкнено)
async def profile_cards_cb(callback: CallbackQuery):
    """Відкрити карточки із профілю."""
    if not callback.message:
        await callback.answer()
        return
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    # Відповідь одразу - інакше клієнт показує «завантаження», поки не завершиться cmd_cards (БД / мережа).
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        await cmd_cards(callback.message)
    except Exception as e:
        try:
            print(f"[start] profile_cards_cb: {e!r}")
        except Exception:
            pass
        try:
            await callback.message.answer(
                "Не вдалося відкрити карточки. Спробуй команду /cards або повтори через хвилину.",
                parse_mode="html",
            )
        except Exception:
            pass


@router_start.callback_query(F.data == "profile_galicia_30s")
async def profile_galicia_30s_cb(callback: CallbackQuery):
    """Єдиний хаб для сюжету / досягнень / карточок."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return

    ensure_db_connection_usable()
    uid = callback.from_user.id
    try:
        row_cards = await _db_fetchone(
            "SELECT COUNT(*) FROM user_story_cards WHERE user_id = %s",
            (uid,),
        )
        cards_count = int((row_cards or [0])[0] or 0)
    except Exception:
        cards_count = 0

    try:
        row_ach = await _db_fetchone(
            """
            SELECT COUNT(*)
            FROM user_achievement_progress
            WHERE user_id = %s AND progress >= required_amount
            """,
            (uid,),
        )
        achievements_count = int((row_ach or [0])[0] or 0)
    except Exception:
        achievements_count = 0

    text = (
        "📜 <b>Сицилія 30-х</b>\n\n"
        "Це точка відліку.\n"
        "Попереду - або велике майбутнє, або забуття в тіні «Сицилійської мафії», "
        "яка не прощає помилок і не приймає сторонніх. "
        "Ваша доля ще не написана, і тільки від ваших рішень залежить, ким ви станете в цьому світі.\n\n"
        f"Ваші досягнення: <b>{achievements_count}</b>\n"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _icon_button("🏆", "Досягнення", "profile_achievements"),
            ],
            [InlineKeyboardButton(text="Повернутися", callback_data="buffshop_back_to_profile")],
        ]
    )
    await callback.message.edit_text(
        emoji_to_premium(text, skip_vip_badges=False),
        reply_markup=kb,
        parse_mode="html",
    )
    await callback.answer()


@router_start.callback_query(F.data == "profile_subscription")
async def profile_subscription_cb(callback: CallbackQuery):
    """Відкрити меню підписки із профілю."""
    if not callback.message:
        await callback.answer()
        return
    from commands.buy import DonateCommand
    donate = DonateCommand()
    await donate.subscription_menu_handler(
        callback.message,
        edit_current=True,
        user_id=callback.from_user.id if callback.from_user else None,
    )
    await callback.answer()


@router_start.callback_query(F.data.startswith("profile_exchange:"))
async def profile_exchange_cb(callback: CallbackQuery):
    """Відкрити обмінник із профілю."""
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    data = callback.data or ""
    try:
        owner_id = int(data.split(":", 1)[1])
    except Exception:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоє меню.", show_alert=True)
        return
    row = await _db_fetchone(
        "SELECT COALESCE(donate_coins, 0), COALESCE(balance, 0) FROM users WHERE id = %s",
        (owner_id,),
    )
    gold_now = int(row[0]) if row else 0
    balance_now = int(row[1]) if row else 0
    text = (
        "Тут золоту знають справжню вартість.\n\n"
        f"Твій баланс: <b>{gold_now}</b> 🪙 | <b>{balance_now}</b> 💵\n\n"
        "Курс: <b>1</b> 🪙 = <b>100</b> 💵\n\n"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _icon_button("🪙", "1 → 💵 100", f"exchange_quick:{owner_id}:1"),
                _icon_button("🪙", "5 → 💵 500", f"exchange_quick:{owner_id}:5"),
            ],
            [_icon_button("🪙", "10 → 💵 1000", f"exchange_quick:{owner_id}:10")],
            [InlineKeyboardButton(text="Своя кількість", callback_data=f"exchange_custom:{owner_id}")],
            [InlineKeyboardButton(text="Повернутися", callback_data="buffshop_owned")],
        ]
    )
    await callback.message.edit_text(emoji_to_premium(text), reply_markup=keyboard, parse_mode="html")
    await callback.answer()


def _is_waiting_exchange_amount(message: Message) -> bool:
    if message.chat.type != "private" or not message.from_user or not message.text:
        return False
    if message.text.strip().startswith("/"):
        return False
    return message.from_user.id in _awaiting_exchange_amount_user_ids


def _is_waiting_sell_buff_amount(message: Message) -> bool:
    if message.chat.type != "private" or not message.from_user or not message.text:
        return False
    if message.text.strip().startswith("/"):
        return False
    return message.from_user.id in _awaiting_sell_buff_amount_by_user


async def _exchange_gold_amount_async(user, amount: int) -> tuple[bool, str]:
    user_id = int(user.id)
    def _run():
        try:
            row = _db_fetchone_sync(
                "SELECT COALESCE(donate_coins, 0), COALESCE(balance, 0) FROM users WHERE id = %s FOR UPDATE",
                (user_id,),
            )
            if not row:
                _db_execute_sync(
                    "INSERT INTO users (id, tg_name, link, balance, donate_coins) VALUES (%s, %s, %s, 0, 0) ON CONFLICT (id) DO NOTHING",
                    (user_id, user.first_name or None, user.username or None),
                )
                conn.commit()
                row = _db_fetchone_sync(
                    "SELECT COALESCE(donate_coins, 0), COALESCE(balance, 0) FROM users WHERE id = %s FOR UPDATE",
                    (user_id,),
                )
            gold = int(row[0]) if row else 0
            if gold < amount:
                conn.rollback()
                return False, f"Недостатньо золота: {gold} 🪙"
            krb_add = amount * 100
            _db_execute_sync(
                "UPDATE users SET donate_coins = donate_coins - %s, balance = balance + %s WHERE id = %s",
                (amount, krb_add, user_id),
            )
            conn.commit()
            return True, f"Обмін: -{amount} 🪙, +{krb_add} 💵"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, "Не вдалося обміняти."
    return await run_db_call_async(_run)


@router_start.callback_query(F.data.startswith("exchange_quick:"))
async def exchange_quick_cb(callback: CallbackQuery):
    """Швидкий обмін золота кнопкою з профілю."""
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    data = callback.data or ""
    try:
        _, owner_id_raw, amount_raw = data.split(":", 2)
        owner_id = int(owner_id_raw)
        amount = int(amount_raw)
    except Exception:
        await callback.answer("Некоректна сума.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоє меню.", show_alert=True)
        return
    if amount <= 0:
        await callback.answer("Некоректна сума.", show_alert=True)
        return

    ok, msg = await _exchange_gold_amount_async(callback.from_user, amount)
    await callback.answer(msg, show_alert=True)
    if ok:
        await profile_exchange_cb(callback)


@router_start.callback_query(F.data.startswith("exchange_custom:"))
async def exchange_custom_cb(callback: CallbackQuery):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    data = callback.data or ""
    try:
        owner_id = int(data.split(":", 1)[1])
    except Exception:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоє меню.", show_alert=True)
        return
    _awaiting_exchange_amount_user_ids.add(owner_id)
    await callback.message.answer("Введи кількість золота для обміну (наприклад: <code>7</code>).", parse_mode="html")
    await callback.answer("Чекаю твою кількість")


@router_start.message(F.func(_is_waiting_exchange_amount))
async def exchange_custom_amount_input(message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    text = (message.text or "").strip()
    try:
        amount = int(text)
    except ValueError:
        await message.answer("Введи число, наприклад: 7")
        return
    if amount <= 0:
        await message.answer("Кількість має бути більшою за 0.")
        return
    ok, msg = await _exchange_gold_amount_async(message.from_user, amount)
    _awaiting_exchange_amount_user_ids.discard(user_id)
    await message.answer(msg, parse_mode="html")


@router_start.callback_query(F.data.startswith("profile_sell_buffs:"))
async def profile_sell_buffs_cb(callback: CallbackQuery):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    data = callback.data or ""
    try:
        owner_id = int(data.split(":", 1)[1])
    except Exception:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоє меню.", show_alert=True)
        return
    await _render_sell_buffs_menu(callback.message, owner_id)
    await callback.answer()


@router_start.callback_query(F.data.startswith("sellbuff:"))
async def sell_buff_one_cb(callback: CallbackQuery):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    data = callback.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    _, owner_raw, buff_id = parts
    try:
        owner_id = int(owner_raw)
    except ValueError:
        await callback.answer("Помилка owner.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоє меню.", show_alert=True)
        return
    from commands.buff_shop import ITEMS
    item = ITEMS.get(str(buff_id))
    if not item:
        await callback.answer("Бафа не знайдено.", show_alert=True)
        return

    sell_one = max(1, int(round(int(item.price) * (95 / 150))))

    # Показуємо вибір частки, яку гравець хоче продати.
    try:
        row = await _db_fetchone(
            """
            SELECT COALESCE(quantity, 1), COALESCE(infinite, FALSE), COALESCE(is_unique, FALSE), COALESCE(buff_name, '')
            FROM user_buffs
            WHERE user_id = %s AND buff_id = %s
            """,
            (owner_id, buff_id),
        )
        if not row:
            await callback.answer("У тебе немає цього бафа.", show_alert=True)
            return

        qty, inf, uniq = int(row[0] or 0), bool(row[1]), bool(row[2])
        buff_name = str(row[3] or "")
        if inf or uniq or qty <= 0:
            await callback.answer("Цей баф не можна продати.", show_alert=True)
            return
    except Exception:
        await callback.answer("Не вдалося отримати дані по бафу.", show_alert=True)
        return

    preset_qty = [1, 2, 3, 5, 10, qty]
    seen_qty: set[int] = set()
    options: list[tuple[int, int]] = []  # (qty, total)
    for q in preset_qty:
        q = int(q)
        if q <= 0:
            continue
        q = min(q, qty)
        if q in seen_qty:
            continue
        seen_qty.add(q)
        options.append((q, sell_one * q))

    kb_rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for q, total in options:
        btn_label = "Вся кількість" if q == qty else f"x{q}"
        current_row.append(
            InlineKeyboardButton(
                text=f"{btn_label} - {total}💵",
                callback_data=f"sellbuff_do:{owner_id}:{buff_id}:{q}",
            )
        )
        if len(current_row) == 2:
            kb_rows.append(current_row)
            current_row = []
    if current_row:
        kb_rows.append(current_row)

    kb_rows.append(
        [InlineKeyboardButton(text="Своя кількість", callback_data=f"sellbuff_custom:{owner_id}:{buff_id}")]
    )
    kb_rows.append([InlineKeyboardButton(text="Назад", callback_data=f"profile_sell_buffs:{owner_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    prompt_text = (
        f"🛒 <b>Яку долю товару продаєте?</b>\n\n"
        f"{item.emoji} <b>{buff_name}</b>\n"
        f"В наявності: <b>{qty}</b>\n"
        f"Ціна за 1: <b>{sell_one}</b> 💵"
    )
    prompt_text = emoji_to_premium(prompt_text, skip_vip_badges=False)
    await callback.message.edit_text(prompt_text, reply_markup=kb, parse_mode="html")
    await callback.answer()


async def _render_sell_buffs_menu(message: Message, owner_id: int):
    """Рендер меню продажу бафів (без парсингу callback_data)."""
    from commands.buff_shop import ITEMS
    rows = await _db_fetchall(
        """
        SELECT ub.buff_id, ub.buff_name, COALESCE(ub.quantity, 1)
        FROM user_buffs ub
        WHERE ub.user_id = %s
          AND COALESCE(ub.is_unique, FALSE) = FALSE
          AND COALESCE(ub.infinite, FALSE) = FALSE
          AND COALESCE(ub.quantity, 1) > 0
        ORDER BY ub.buff_name ASC
        LIMIT 25
        """,
        (owner_id,),
    )
    rows = rows or []
    if not rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Повернутися", callback_data="buffshop_owned")]])
        await message.edit_text("🌍 У тебе немає зайвих бафів для обміну.", reply_markup=kb)
        return
    kb_rows = []
    for buff_id, buff_name, qty in rows:
        item = ITEMS.get(str(buff_id))
        if not item:
            continue
        sell_one = max(1, int(round(int(item.price) * (95 / 150))))
        cid = custom_emoji_id_for_symbol(str(item.emoji))
        label = f"{buff_name} (x{qty}) за {sell_one}💵"
        if cid:
            kb_rows.append(
                [InlineKeyboardButton(text=label, callback_data=f"sellbuff:{owner_id}:{buff_id}", icon_custom_emoji_id=cid)]
            )
        else:
            kb_rows.append(
                [InlineKeyboardButton(text=f"{item.emoji} {label}", callback_data=f"sellbuff:{owner_id}:{buff_id}")]
            )
    kb_rows.append([InlineKeyboardButton(text="Повернутися", callback_data="buffshop_owned")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows[:30])
    text = (
        "🌍 <b>Світ має ціну.</b>\n\n"
        "Ми маємо пропозицію. На цьому ринку торгують не лише товаром, а й можливостями.\n"
        "Позбувайтеся зайвих бафів, поки вони мають вартість."
    )
    await message.edit_text(text, reply_markup=kb, parse_mode="html")


async def _sell_buff_amount_async(owner_id: int, buff_id: str, sell_qty: int, sell_one: int) -> tuple[bool, str, int]:
    """Transactional buff sell; returns (ok, error, payout)."""
    def _run():
        try:
            row = _db_fetchone_sync(
                """
                SELECT COALESCE(quantity, 1), COALESCE(infinite, FALSE), COALESCE(is_unique, FALSE)
                FROM user_buffs
                WHERE user_id = %s AND buff_id = %s
                FOR UPDATE
                """,
                (owner_id, buff_id),
            )
            if not row:
                conn.rollback()
                return False, "У тебе немає цього бафа.", 0

            current_qty, inf, uniq = int(row[0] or 0), bool(row[1]), bool(row[2])
            if inf or uniq or current_qty <= 0:
                conn.rollback()
                return False, "Цей баф не можна продати.", 0

            sell_qty_local = min(int(sell_qty), current_qty)
            if sell_qty_local <= 0:
                conn.rollback()
                return False, "Некоректна кількість.", 0

            if current_qty > sell_qty_local:
                _db_execute_sync(
                    "UPDATE user_buffs SET quantity = quantity - %s WHERE user_id = %s AND buff_id = %s",
                    (sell_qty_local, owner_id, buff_id),
                )
            else:
                _db_execute_sync(
                    "DELETE FROM user_buffs WHERE user_id = %s AND buff_id = %s",
                    (owner_id, buff_id),
                )

            payout = int(sell_one) * sell_qty_local
            _db_execute_sync(
                "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s",
                (payout, owner_id),
            )
            conn.commit()
            return True, "", payout
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, "Не вдалося продати.", 0
    return await run_db_call_async(_run)


@router_start.callback_query(F.data.startswith("sellbuff_do:"))
async def sell_buff_do_cb(callback: CallbackQuery):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    data = callback.data or ""
    parts = data.split(":", 3)
    if len(parts) != 4:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    _, owner_raw, buff_id, qty_raw = parts
    try:
        owner_id = int(owner_raw)
        sell_qty = int(qty_raw)
    except ValueError:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоє меню.", show_alert=True)
        return
    if sell_qty <= 0:
        await callback.answer("Некоректна кількість.", show_alert=True)
        return

    from commands.buff_shop import ITEMS
    item = ITEMS.get(str(buff_id))
    if not item:
        await callback.answer("Бафа не знайдено.", show_alert=True)
        return
    sell_one = max(1, int(round(int(item.price) * (95 / 150))))

    ok, error_text, payout = await _sell_buff_amount_async(owner_id, buff_id, sell_qty, sell_one)
    if not ok:
        await callback.answer(error_text or "Не вдалося продати.", show_alert=True)
        return
    await _render_sell_buffs_menu(callback.message, owner_id)
    await callback.answer(f"Готово ✓ +{payout}💵", show_alert=True)


@router_start.callback_query(F.data.startswith("sellbuff_custom:"))
async def sell_buff_custom_cb(callback: CallbackQuery):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в ПП.", show_alert=True)
        return
    if not callback.from_user:
        await callback.answer()
        return
    data = callback.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    _, owner_raw, buff_id = parts
    try:
        owner_id = int(owner_raw)
    except ValueError:
        await callback.answer("Помилка owner.", show_alert=True)
        return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоє меню.", show_alert=True)
        return
    _awaiting_sell_buff_amount_by_user[owner_id] = (owner_id, str(buff_id))
    await callback.message.answer("Введіть кількість бафа для продажу (наприклад: <code>7</code>).", parse_mode="html")
    await callback.answer("Чекаю вашу кількість")


@router_start.message(F.func(_is_waiting_sell_buff_amount))
async def sell_buff_custom_amount_input(message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    pending = _awaiting_sell_buff_amount_by_user.get(user_id)
    if not pending:
        return
    owner_id, buff_id = pending
    if user_id != owner_id:
        _awaiting_sell_buff_amount_by_user.pop(user_id, None)
        return
    text = (message.text or "").strip()
    try:
        sell_qty = int(text)
    except ValueError:
        await message.answer("Введіть ціле число, наприклад: 5")
        return
    if sell_qty <= 0:
        await message.answer("Кількість має бути більшою за 0.")
        return

    from commands.buff_shop import ITEMS
    item = ITEMS.get(str(buff_id))
    if not item:
        _awaiting_sell_buff_amount_by_user.pop(user_id, None)
        await message.answer("Бафа не знайдено.")
        return
    sell_one = max(1, int(round(int(item.price) * (95 / 150))))
    row_qty = await _db_fetchone(
        "SELECT COALESCE(quantity, 1) FROM user_buffs WHERE user_id = %s AND buff_id = %s",
        (owner_id, buff_id),
    )
    current_qty = int(row_qty[0] or 0) if row_qty else 0
    if current_qty > 0 and sell_qty > current_qty:
        await message.answer(f"У тебе лише {current_qty}. Введи менше або рівно цій кількості.")
        return

    ok, error_text, payout = await _sell_buff_amount_async(owner_id, buff_id, sell_qty, sell_one)
    _awaiting_sell_buff_amount_by_user.pop(user_id, None)
    if not ok:
        await message.answer(error_text or "Не вдалося продати. Спробуй ще раз.")
        return
    await message.answer(f"Готово ✓ Продано x{sell_qty}, нараховано {payout}💵")


@router_start.callback_query(F.data == "transfer_gold_start")
async def transfer_gold_start_cb(callback: CallbackQuery):
    """Вибір суми переказу золотих монет на підписку."""
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer()
        return
    row = await _db_fetchone(
        "SELECT COALESCE(donate_coins, 0) FROM users WHERE id = %s",
        (callback.from_user.id,),
    )
    gold = int(row[0]) if row else 0
    if gold < 5:
        await callback.answer("У вас менше 5 золотих монет. Переказ недоступний.", show_alert=True)
        return
    text = (
        "🪙 <b>Перевести золоті монети на підписку</b>\n\n"
        f"У вас: <b>{gold}</b> 🪙\n\n"
        "Оберіть суму для переказу на рахунок бота (підтримка підписок):"
    )
    amounts = [5, 10, 25, 50, 100]
    buttons = [
        [InlineKeyboardButton(text=f"🪙 {a}", callback_data=f"transfer_gold_{a}")]
        for a in amounts
        if a <= gold
    ]
    if not buttons:
        await callback.answer("Недостатньо золотих монет.", show_alert=True)
        return
    buttons.append([InlineKeyboardButton(text="Повернутися", callback_data="buffshop_back_to_profile")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="html")
    await callback.answer()


@router_start.callback_query(F.data.startswith("transfer_gold_"))
async def transfer_gold_confirm_cb(callback: CallbackQuery):
    """Виконання переказу золотих на фонд підписок."""
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer()
        return
    data = callback.data or ""
    if not data.startswith("transfer_gold_"):
        await callback.answer()
        return
    try:
        amount = int(data.replace("transfer_gold_", ""))
    except ValueError:
        await callback.answer()
        return
    if amount < 1:
        await callback.answer()
        return
    user_id = callback.from_user.id
    if not await deduct_user_gold_async(user_id, amount):
        await callback.answer("Недостатньо золотих монет або помилка.", show_alert=True)
        return
    add_gold_to_subscription_fund(amount)
    await callback.message.edit_text(
        f"Дякуємо! Ви перевели <b>{amount}</b> 🪙 на підтримку підписок.\n\n"
        "Ваш внесок допоможе розвивати бота.",
        parse_mode="html",
    )
    await callback.answer("Переказ виконано ✓")

