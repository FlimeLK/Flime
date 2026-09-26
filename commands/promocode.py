"""
Система промокодів: активація через /promocode <код>.
Власники створюють промокоди через /capone_admin.
"""

import re
import json
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message
from database.database import cursor, conn
from commands.start import add_user_to_db
from premium_emoji import emoji_to_premium


router_promocode = Router()


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_execute(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0


def _is_promocode_command(message: Message) -> bool:
    """Чи є повідомлення командою /promocode (з аргументом чи без)."""
    text = (message.text or "").strip()
    if not text:
        return False
    # /promocode або /promocode@BotName, з аргументом чи без
    return text.startswith("/promocode") and (len(text) <= 10 or text[10:11] in (" ", "\n", "@"))


def _normalize_code(text: str) -> str:
    """Нормалізація коду: обрізати пробіли, замінити множинні пробіли на один, у нижній регістр для порівняння."""
    if not text or not isinstance(text, str):
        return ""
    s = re.sub(r"\s+", " ", text.strip()).lower()
    return s


def _get_promocode_by_code(normalized: str):
    """Повертає рядок (id, code, name, ...) або None. Порівняння без урахування регістру."""
    return _db_fetchone("""
        SELECT id, code, name, max_activations, current_activations,
               reward_balance, reward_gold, reward_buffs,
               reward_subscription_item_id, reward_subscription_days, is_active
        FROM promocodes
        WHERE LOWER(TRIM(code)) = %s
        LIMIT 1
    """, (normalized,))


def _user_already_activated(promocode_id: int, user_id: int) -> bool:
    row = _db_fetchone(
        "SELECT 1 FROM promocode_activations WHERE promocode_id = %s AND user_id = %s",
        (promocode_id, user_id),
    )
    return row is not None


def _apply_rewards(user_id: int, row, bot: Bot) -> list:
    """
    Застосовує нагороди промокоду для user_id.
    row = (id, code, name, max_activations, current_activations, reward_balance, reward_gold, reward_buffs, reward_subscription_item_id, reward_subscription_days, is_active)
    Повертає список рядків для повідомлення користувачу (що отримано).
    """
    from datetime import datetime, timedelta
    from commands.buff_shop import ITEMS

    rewards_text = []
    promocode_id, code, name, max_act, cur_act, r_balance, r_gold, r_buffs_json, r_sub_item, r_sub_days, _ = row

    # Користувач має існувати в users
    row = _db_fetchone("SELECT id FROM users WHERE id = %s", (user_id,))
    if not row:
        _db_execute("INSERT INTO users (id, balance, donate_coins) VALUES (%s, 0, 0) ON CONFLICT (id) DO NOTHING", (user_id,))
        conn.commit()

    # Ліри
    if r_balance and r_balance > 0:
        _db_execute(
            "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s",
            (r_balance, user_id),
        )
        rewards_text.append(f"💰 {r_balance} лір")

    # Золоті монети
    if r_gold and r_gold > 0:
        _db_execute(
            "UPDATE users SET donate_coins = COALESCE(donate_coins, 0) + %s WHERE id = %s",
            (r_gold, user_id),
        )
        rewards_text.append(f"🪙 {r_gold} золотих монет")

    # Бафи (reward_buffs = JSON array of {buff_id, buff_name, quantity})
    if r_buffs_json:
        try:
            buffs = r_buffs_json if isinstance(r_buffs_json, list) else json.loads(r_buffs_json or "[]")
        except (TypeError, json.JSONDecodeError):
            buffs = []
        for entry in buffs:
            buff_id = entry.get("buff_id")
            buff_name = entry.get("buff_name") or ""
            qty = max(1, int(entry.get("quantity", 1)))
            item = ITEMS.get(buff_id) if buff_id else None
            if not item:
                continue
            metadata = {
                "category": item.category.value,
                "item_type": item.item_type.value,
                "activation_time": item.activation_time.value,
                "cooldown": item.cooldown.value,
                "priority": item.priority,
            }
            if item.effect_data:
                metadata["effect_data"] = item.effect_data
            _db_execute("""
                INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity)
                VALUES (%s, %s, %s, FALSE, %s::jsonb, %s)
                ON CONFLICT (user_id, buff_id) DO UPDATE
                  SET buff_name = EXCLUDED.buff_name, metadata = EXCLUDED.metadata,
                      quantity = user_buffs.quantity + EXCLUDED.quantity
            """, (user_id, item.item_id, item.name, json.dumps(metadata), qty))
            rewards_text.append(f"📦 {item.emoji} {item.name} x{qty}")

    # Підписка (дні або тип з ShopManager)
    if r_sub_item or (r_sub_days and r_sub_days > 0):
        from commands.buy import ShopManager

        now = datetime.now()
        if r_sub_item and ShopManager.get_item(r_sub_item):
            item = ShopManager.get_item(r_sub_item)
            days = r_sub_days if r_sub_days and r_sub_days > 0 else (item.duration_days if item else 0)
        elif r_sub_days and r_sub_days > 0:
            days = r_sub_days
            r_sub_item = "subscription_1month"  # fallback type for display
        else:
            days = 0
        if days > 0:
            end_date = now + timedelta(days=days)
            exists = _db_fetchone("SELECT user_id FROM subscriptions WHERE user_id = %s", (user_id,))
            sub_type = r_sub_item or "promo"
            if exists:
                _db_execute("""
                    UPDATE subscriptions
                    SET subscription_type = %s, subscription_end = GREATEST(subscription_end, %s), is_active = TRUE, updated_at = %s
                    WHERE user_id = %s
                """, (sub_type, end_date, now, user_id))
            else:
                _db_execute("""
                    INSERT INTO subscriptions (user_id, subscription_type, subscription_start, subscription_end, is_active, is_purchased)
                    VALUES (%s, %s, %s, %s, TRUE, FALSE)
                """, (user_id, sub_type, now, end_date))
            rewards_text.append(f"🎫 Підписка на {days} дн.")

    conn.commit()
    return rewards_text


@router_promocode.message(F.chat.type == "private", F.text, F.func(_is_promocode_command))
async def cmd_promocode(message: Message, bot: Bot):
    """Активація промокоду: /promocode <код> (слова, які вказав власник при створенні)."""
    user_id = message.from_user.id if message.from_user else 0
    if not user_id:
        await message.answer("❌ Помилка: не вдалося визначити користувача.", parse_mode="html")
        return

    text = (message.text or "").strip()
    # Відрізати команду ( /promocode або /promocode@BotName )
    if text.startswith("/promocode"):
        rest = text[10:].strip()
        if rest.startswith("@"):
            idx = rest.find(" ")
            rest = (rest[idx + 1:] if idx >= 0 else "").strip()
    else:
        rest = ""
    code_input = rest.strip() if rest else ""
    if not code_input:
        await message.answer(
            "🎟 <b>Промокод</b>\n\n"
            "Введи команду разом із кодом:\n"
            "<code>/promocode слова коду</code>\n\n"
            "Приклад: <code>/promocode весняний бонус</code>",
            parse_mode="html",
        )
        return
    normalized = _normalize_code(code_input)
    if not normalized:
        await message.answer("❌ Введі код після команди. Приклад: <code>/promocode весняний бонус</code>", parse_mode="html")
        return

    await add_user_to_db(message)

    row = _get_promocode_by_code(normalized)
    if not row:
        await message.answer("❌ Промокод не знайдено або введено невірно. Перевір написання.", parse_mode="html")
        return

    promocode_id = row[0]
    is_active = row[10]
    if not is_active:
        await message.answer("❌ Цей промокод більше не дійсний.", parse_mode="html")
        return

    max_activations = row[3]
    current_activations = row[4]
    if current_activations >= max_activations:
        await message.answer("❌ Ліміт активацій цього промокоду вичерпано.", parse_mode="html")
        return

    if _user_already_activated(promocode_id, user_id):
        await message.answer("❌ Ти вже використовував цей промокод.", parse_mode="html")
        return

    try:
        rewards_text = _apply_rewards(user_id, row, bot)
        _db_execute(
            "INSERT INTO promocode_activations (promocode_id, user_id) VALUES (%s, %s) ON CONFLICT (promocode_id, user_id) DO NOTHING",
            (promocode_id, user_id),
        )
        _db_execute(
            "UPDATE promocodes SET current_activations = current_activations + 1 WHERE id = %s",
            (promocode_id,),
        )
        conn.commit()
        # Якщо всі активації вичерпано - автоматично видаляємо промокод
        new_count = current_activations + 1
        if new_count >= max_activations:
            _db_execute("DELETE FROM promocode_activations WHERE promocode_id = %s", (promocode_id,))
            _db_execute("DELETE FROM promocodes WHERE id = %s", (promocode_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        await message.answer("❌ Помилка при активації. Спробуй пізніше або звернись до підтримки.", parse_mode="html")
        return

    if not rewards_text:
        rewards_str = "Нагороди не було налаштовано."
    else:
        rewards_str = "\n".join(f"• {t}" for t in rewards_text)

    name = row[2] or row[1]
    await message.answer(
        emoji_to_premium(
            f"✅ <b>Промокод активовано!</b>\n\n"
            f"🎟 <b>{name}</b>\n\n"
            f"Ти отримав:\n{rewards_str}"
        ),
        parse_mode="html",
    )
