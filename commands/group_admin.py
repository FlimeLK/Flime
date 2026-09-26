"""
Адміни груп з рівнями прав.
+адмін [рівень] @user - додати адміна (1=мут, 2=бан, 3=construct_event, 4=співвласник).
Максимальний рівень, який можна призначити - 4. Рівень 5 недоступний для призначення.
-адмін @user - зняти права.

Хто може ким керувати:
- Власник групи, адмін 4 рівня, власник бота — повний доступ (рівні 1–4, зняття будь-кого з БД-адмінів).
- Старший адміністратор (рівень 3) — лише +адмін 1/2 та -адмін для тих, хто має в БД рівень 1 або 2
  (не може змінювати/знімати адмінів 3–4 рівня).

Власник групи (Telegram) має максимальний рівень (4). Власник бота має невидимий рівень 5 у всіх групах.
Усі адміни мають імунітет від муту/бану.
"""

import re
import random
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import Message, CallbackQuery, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from database.database import (
    cursor,
    conn,
    get_group_admin_level,
    set_group_admin,
    remove_group_admin,
    get_group_admins_list,
)
from game.game_state_manager import game_state_manager
from premium_emoji import emoji_to_premium
from commands.construct_event import get_active_construct_event

router_group_admin = Router()


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_execute(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0

# ID власників бота (мають невидимий рівень 5 у всіх групах)
BOT_OWNER_IDS = [1859870653]

# Тільки групи/супергрупи (aiogram повертає enum ChatType)
GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)

# Відповіді, коли в групі пишуть саме одне слово «Мафія» (щоб було зрозуміло, що бот працює)
MAFIA_ACK_REPLIES = [
    "🎩 Мафія чує тебе. Я на зв'язку!",
    "🃏 Мафія в місті. Пиши /play, коли готові грати!",
    "🌙 Ніч падає на місто… Мафія не спить. Я тут!",
    "👔 Дон бачить усіх. Бот на місці!",
    "🖤 Мафія на лінії. Що скажеш?",
]

# Рівні: 1 - мут, 2 - бан, 3 - construct_event, 4 - співвласник, 5 - власник бота (невидимий)
ADMIN_LEVEL_MUTE = 1
ADMIN_LEVEL_BAN = 2
ADMIN_LEVEL_CONSTRUCT = 3
ADMIN_LEVEL_COOWNER = 4
ADMIN_LEVEL_BOT_OWNER = 5  # Невидимий рівень для власника бота
MAX_WARNS = 5
WARN_AUTO_MUTE_SECONDS = 60 * 60


def _set_group_theme_flag(chat_id: int, column: str, value: bool) -> None:
    """Оновлює тематичний прапорець одразу для всіх записів admin_panel цієї групи."""
    _db_execute(f"UPDATE admin_panel SET {column} = %s WHERE group_id = %s", (value, chat_id))
    conn.commit()


def _ensure_warns_table() -> None:
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS group_user_warns (
            group_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            warns INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, user_id)
        )
        """
    )
    conn.commit()


def _get_warns_count(group_id: int, user_id: int) -> int:
    _ensure_warns_table()
    row = _db_fetchone(
        "SELECT warns FROM group_user_warns WHERE group_id = %s AND user_id = %s",
        (group_id, user_id),
    )
    return int(row[0]) if row else 0


def _set_warns_count(group_id: int, user_id: int, warns: int) -> int:
    _ensure_warns_table()
    safe_warns = max(0, min(MAX_WARNS, int(warns)))
    _db_execute(
        """
        INSERT INTO group_user_warns (group_id, user_id, warns, updated_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (group_id, user_id)
        DO UPDATE SET warns = EXCLUDED.warns, updated_at = CURRENT_TIMESTAMP
        """,
        (group_id, user_id, safe_warns),
    )
    conn.commit()
    return safe_warns


def _increment_warns(group_id: int, user_id: int) -> int:
    current = _get_warns_count(group_id, user_id)
    return _set_warns_count(group_id, user_id, current + 1)


def _decrement_warns(group_id: int, user_id: int, by: int = 1) -> int:
    """Зняти `by` warn-ів (за замовчуванням 1). Повертає новий лічильник (>=0)."""
    current = _get_warns_count(group_id, user_id)
    return _set_warns_count(group_id, user_id, current - max(1, by))


async def _get_effective_admin_level(bot: Bot, group_id: int, user_id: int) -> int:
    """
    Повертає ефективний рівень адміна: 5 для власника бота (невидимий),
    4 для власника групи (CREATOR), інакше рівень з group_admins (0 якщо не адмін).
    """
    # Власник бота завжди має максимальний рівень 5 у всіх групах
    if user_id in BOT_OWNER_IDS:
        return ADMIN_LEVEL_BOT_OWNER
    
    try:
        member = await bot.get_chat_member(group_id, user_id)
        if member.status == ChatMemberStatus.CREATOR:
            return ADMIN_LEVEL_COOWNER
    except Exception:
        pass
    return get_group_admin_level(group_id, user_id)


async def _can_manage_admins(bot: Bot, group_id: int, user_id: int) -> bool:
    """Чи може користувач взагалі займатись +адмін/-адмін (рівень 3+ або власник)."""
    level = await _get_effective_admin_level(bot, group_id, user_id)
    return level >= ADMIN_LEVEL_CONSTRUCT


async def _admin_promotion_allowed(
    bot: Bot,
    chat_id: int,
    executor_id: int,
    target_id: int,
    *,
    is_remove: bool,
    new_level: int | None = None,
) -> tuple[bool, str]:
    """
    Обмеження для старших адмінів (ефективний рівень 3): лише 1–2 та без зміни старших.
    Повертає (True, "") або (False, текст_помилки).
    """
    ex = await _get_effective_admin_level(bot, chat_id, executor_id)
    if ex < ADMIN_LEVEL_CONSTRUCT:
        return (
            False,
            "Немає доступу до керування адмінами.",
        )
    if ex >= ADMIN_LEVEL_COOWNER:
        return (True, "")

    tgt_before = get_group_admin_level(chat_id, target_id)
    if is_remove:
        if tgt_before not in (ADMIN_LEVEL_MUTE, ADMIN_LEVEL_BAN):
            return (
                False,
                "Старший адміністратор (рівень 3) може знімати права лише з адмінів 1–2 рівня. "
                "Для зняття старших адмінів звернись до власника групи або адміна 4 рівня.",
            )
        return (True, "")

    if new_level is None:
        return (False, "Внутрішня помилка: не вказано рівень.")
    if new_level > ADMIN_LEVEL_BAN:
        return (
            False,
            "Старший адміністратор може призначати лише рівні <b>1</b> (мут) та <b>2</b>. "
            "Рівні 3–4 — лише власник групи або адмін 4 рівня.",
        )
    if tgt_before >= ADMIN_LEVEL_CONSTRUCT:
        return (
            False,
            "Немає прав змінювати рівень адміністратора 3 або 4 рівня.",
        )
    return (True, "")


async def _has_permission(bot: Bot, group_id: int, user_id: int, required_level: int) -> bool:
    """Чи має користувач потрібний рівень (включно з власником)."""
    return await _get_effective_admin_level(bot, group_id, user_id) >= required_level


async def _is_admin_immune(bot: Bot, group_id: int, user_id: int) -> bool:
    """Чи має користувач імунітет (власник бота, власник групи, Telegram-адмін або будь-який рівень у group_admins)."""
    # Власник бота завжди має імунітет
    if user_id in BOT_OWNER_IDS:
        return True
    
    try:
        member = await bot.get_chat_member(group_id, user_id)
        if member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR):
            return True
    except Exception:
        pass
    return get_group_admin_level(group_id, user_id) >= 1


async def _resolve_target_user(message: Message, bot: Bot) -> int | None:
    """Повертає user_id цільового користувача з повідомлення (reply, mention або text_mention)."""
    # Спочатку перевіряємо reply
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    
    # Перевіряємо entities для mentions
    if message.entities:
        for e in message.entities:
            entity_type = getattr(e, "type", None)
            
            # text_mention - коли є пряме посилання на користувача (містить user_id)
            if entity_type == "text_mention" and getattr(e, "user", None):
                return e.user.id
            
            # mention - коли є @username (може не містити user_id, потрібно шукати)
            if entity_type == "mention":
                if message.text:
                    username = message.text[e.offset:e.offset + e.length]
                    if username.startswith("@"):
                        username = username[1:].lower()  # Прибираємо @ і робимо lowercase
                        
                        # Спочатку шукаємо в базі даних
                        try:
                            result = _db_fetchone("SELECT id FROM users WHERE LOWER(link) = %s", (username,))
                            if result:
                                return result[0]
                        except Exception:
                            pass
                        
                        # Якщо не знайшли в БД, шукаємо серед адмінів групи
                        try:
                            chat_id = message.chat.id
                            admins = await bot.get_chat_administrators(chat_id)
                            for admin in admins:
                                if admin.user.username and admin.user.username.lower() == username:
                                    return admin.user.id
                        except Exception:
                            pass
                        
                        # Fallback: пробуємо резолв через Telegram API за @username
                        try:
                            chat_obj = await bot.get_chat(f"@{username}")
                            if getattr(chat_obj, "id", None):
                                return int(chat_obj.id)
                        except Exception:
                            pass
    
    # Якщо не знайшли через entities, спробуємо витягнути username з тексту вручну
    if message.text:
        import re
        # Шукаємо @username в тексті
        mention_match = re.search(r"@(\w+)", message.text)
        if mention_match:
            username = mention_match.group(1).lower()
            
            # Шукаємо в базі даних
            try:
                result = _db_fetchone("SELECT id FROM users WHERE LOWER(link) = %s", (username,))
                if result:
                    return result[0]
            except Exception:
                pass
            
            # Шукаємо серед адмінів групи
            try:
                chat_id = message.chat.id
                admins = await bot.get_chat_administrators(chat_id)
                for admin in admins:
                    if admin.user.username and admin.user.username.lower() == username:
                        return admin.user.id
            except Exception:
                pass
            
            # Fallback: пробуємо резолв через Telegram API за @username
            try:
                chat_obj = await bot.get_chat(f"@{username}")
                if getattr(chat_obj, "id", None):
                    return int(chat_obj.id)
            except Exception:
                pass
    
    return None


def _parse_mute_duration(text: str) -> tuple[int | None, str]:
    """
    Парсить час муту з тексту команди.
    Підтримка форматів: 10m, 30m, 1h, 2h, 15s, 1d тощо.
    Повертає (секунди, залишок тексту без часу).
    """
    if not text:
        return (None, text)
    
    # Шукаємо патерн: число + буква (m, h, d, s)
    # Приклади: 10m, 1h, 30s, 2d
    pattern = r'(\d+)\s*([smhd])'
    match = re.search(pattern, text, re.I)
    
    if match:
        value = int(match.group(1))
        unit = match.group(2).lower()
        
        # Конвертуємо в секунди
        if unit == 's':
            seconds = value
        elif unit == 'm':
            seconds = value * 60
        elif unit == 'h':
            seconds = value * 3600
        elif unit == 'd':
            seconds = value * 86400
        else:
            return (None, text)
        
        # Видаляємо знайдений час з тексту
        remaining = text[:match.start()] + text[match.end():]
        remaining = remaining.strip()
        
        return (seconds, remaining)
    
    return (None, text)


def _parse_ban_duration_and_reason(text: str) -> tuple[int | None, str]:
    """
    Парсить тривалість бану й причину.
    Підтримка: 10s, 30m, 2h, 7d, 2mo, 1y.
    Якщо час не вказано - повертає (None, reason) => бан назавжди.
    """
    raw = (text or "").strip()
    if not raw:
        return (None, "")
    parts = raw.split(maxsplit=1)
    token = parts[0].strip().lower()
    reason = parts[1].strip() if len(parts) > 1 else ""

    m = re.fullmatch(r"(\d+)\s*(s|m|h|d|mo|mon|month|months|y|yr|year|years)", token, re.I)
    if not m:
        return (None, raw)

    value = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "s":
        seconds = value
    elif unit == "m":
        seconds = value * 60
    elif unit == "h":
        seconds = value * 3600
    elif unit == "d":
        seconds = value * 86400
    elif unit in ("mo", "mon", "month", "months"):
        seconds = value * 30 * 86400
    else:  # y / yr / year / years
        seconds = value * 365 * 86400
    return (seconds, reason)


def _extract_target_id_from_text(text: str) -> int | None:
    """Витягує user_id з тексту команди, якщо він вказаний явно."""
    if not text:
        return None
    # Пропускаємо перше слово (команда), далі шукаємо перше ціле число.
    parts = text.strip().split()
    for token in parts[1:]:
        t = token.strip().rstrip(",.;")
        if re.fullmatch(r"\d{5,20}", t):
            try:
                return int(t)
            except Exception:
                return None
    return None


async def _resolve_target_user_with_id_fallback(message: Message, bot: Bot) -> int | None:
    """Reply/mention/text_mention/@username або явний user_id у тексті."""
    target_id = await _resolve_target_user(message, bot)
    if target_id:
        return target_id
    return _extract_target_id_from_text(message.text or "")


def _parse_admin_command(text: str) -> tuple[int | None, str]:
    """
    Парсить +адмін [рівень] або -адмін.
    Повертає (рівень, залишок тексту). Для +адмін рівень 1-4 (максимум 4, рівень 5 недоступний).
    """
    text = (text or "").strip()
    # +адмін або +адмін 1 тощо
    plus = re.match(r"^\+адмін\s+(\d+)\s*(.*)$", text, re.I)
    if plus:
        level = int(plus.group(1))
        # Максимальний рівень - 4 (рівень 5 тільки для власника бота, не можна видати)
        if 1 <= level <= 4:
            return (level, plus.group(2).strip())
        # Якщо рівень > 4, повертаємо None (помилка буде показана в handler)
        return (None, text)
    if re.match(r"^\+адмін\s*$", text, re.I):
        return (None, "")  # немає рівня
    minus = re.match(r"^\-адмін\s*(.*)$", text, re.I)
    if minus:
        return (None, minus.group(1).strip())
    return (None, text)


def _parse_slash_admin_args(text: str) -> tuple[bool, int | None]:
    """
    Парсить /адмін ... або /admin ...
    Повертає (is_remove, level).
    Підтримка:
    - /адмін add 1|2|3|4
    - /адмін 1|2|3|4            (вважаємо add)
    - /адмін del|remove|rm      (вважаємо del)
    """
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return (False, None)
    parts = raw.split()
    if not parts:
        return (False, None)
    args = parts[1:]
    if not args:
        return (False, None)

    op = args[0].lower()
    if op in ("del", "delete", "remove", "rm", "minus", "-"):
        return (True, None)
    if op in ("add", "plus", "+"):
        if len(args) >= 2 and args[1].isdigit():
            lvl = int(args[1])
            return (False, lvl if 1 <= lvl <= 4 else None)
        return (False, None)
    if op.isdigit():
        lvl = int(op)
        return (False, lvl if 1 <= lvl <= 4 else None)
    return (False, None)


def _is_exact_mafia_word(message: Message) -> bool:
    """Тільки група і саме одне слово «Мафія» (без слеша, без інших слів)."""
    if not message.text or str(message.text).strip().startswith("/"):
        return False
    return str(message.text).strip().lower() == "мафія"


def _filter_plus_minus_admin(message: Message) -> bool:
    """Тільки повідомлення, що починаються з +адмін або -адмін (щоб не перехоплювати «ХтоАдмін»)."""
    # Логування для діагностики
    if message.text and ("+адмін" in message.text.lower() or "-адмін" in message.text.lower()):
        print(f"[group_admin] 🔍 _filter_plus_minus_admin викликано! chat_id={message.chat.id}, text='{message.text[:50]}'")
    
    if not message.text:
        return False
    text = (message.text or "").strip().lower()
    result = text.startswith("+адмін") or text.startswith("-адмін")
    if result:
        print(f"[group_admin]  _filter_plus_minus_admin: знайдено команду '{text[:20]}' в чаті {message.chat.id}")
    else:
        if message.text and ("+адмін" in message.text.lower() or "-адмін" in message.text.lower()):
            print(f"[group_admin]  _filter_plus_minus_admin: команда знайдена, але не починається з неї! text='{text[:30]}'")
    return result


def _check_hto_admin(message: Message) -> bool:
    """Перевірка чи це «ХтоАдмін» (не команда)."""
    if not message.text:
        return False
    text = message.text.strip()
    if text.startswith("/"):
        return False
    return _is_hto_admin_text(text)


@router_group_admin.message(
    F.chat.type.in_(GROUP_TYPES),
    F.text,
    F.func(_check_hto_admin)
)
async def text_hto_admin_handler(message: Message, bot: Bot):
    """Список адмінів по тексту «ХтоАдмін» (без слеша)."""
    try:
        await _reply_admin_list(message.chat.id, bot, message)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await message.reply(f"Помилка: {e}")
        except Exception:
            pass


# Фільтр для команди /адміни (fallback, якщо Command filter не спрацював)
def _is_admins_command(message: Message) -> bool:
    """Перевірка, що це команда /адміни (fallback для Command filter)."""
    if not message.text:
        return False
    text = message.text.strip()
    if not text.startswith("/"):
        return False
    cmd = text[1:].split()[0].lower() if text[1:] else ""
    return cmd in ("адміни", "admins", "хто_адмін", "хто_админ")

# Окремий handler для +адмін/-адмін з більш специфічним фільтром (спрацьовує першим)
@router_group_admin.message(
    F.chat.type.in_(GROUP_TYPES),
    F.text,
    F.func(_filter_plus_minus_admin)
)
async def admin_command_handler(message: Message, bot: Bot):
    """Handler для +адмін/-адмін команд."""
    try:
        print(f"[group_admin] 🔵 admin_command_handler викликано! chat_id={message.chat.id}, user_id={message.from_user.id}, text='{message.text}'")
        
        # Додаткова перевірка на всяк випадок
        text = (message.text or "").strip()
        if not text:
            print(f"[group_admin]  Пустий текст")
            return
        
        # Перевірка, що це дійсно команда +адмін або -адмін
        text_lower = text.lower()
        if not (text_lower.startswith("+адмін") or text_lower.startswith("-адмін")):
            print(f"[group_admin]  Текст не починається з +адмін або -адмін: '{text_lower[:20]}'")
            return
        
        print(f"[group_admin]  Обробляємо команду: '{text_lower[:30]}'")
        
        chat_id = message.chat.id
        
        level, rest = _parse_admin_command(text)
        is_remove = text_lower.startswith("-адмін")
        
        user_id = message.from_user.id
        
        # Рівень 3+ (старші адміни з обмеженнями — див. _admin_promotion_allowed)
        if not await _can_manage_admins(bot, chat_id, user_id):
            await message.reply(
                "Керувати адмінами можуть власник групи, адмін 4 рівня або старший адміністратор (рівень 3). "
                "Рівень 3 може лише <code>+адмін 1</code>/<code>+адмін 2</code> та знімати адмінів 1–2 рівня.",
                parse_mode="html",
            )
            return
        
        target_id = await _resolve_target_user(message, bot)
        if not target_id:
            if is_remove:
                await message.reply("Відповідь на повідомлення користувача або познач його (mention).")
            else:
                await message.reply("Використання: <code>+адмін 1</code> (або 2/3/4) та reply на повідомлення користувача або познач його через mention.", parse_mode="html")
            return
        
        if is_remove:
            if get_group_admin_level(chat_id, target_id) == 0:
                await message.reply("Цей користувач не є адміном бота в цій групі.")
                return
            ok_rm, err_rm = await _admin_promotion_allowed(
                bot, chat_id, user_id, target_id, is_remove=True
            )
            if not ok_rm:
                await message.reply(err_rm, parse_mode="html")
                return
            remove_group_admin(chat_id, target_id)
            await message.reply(" Права адміна знято.")
            return
        
        if level is None:
            # Перевірка, чи користувач спробував вказати рівень > 4
            if "+адмін" in text_lower:
                # Спробуємо витягнути число після +адмін
                import re
                match = re.search(r"\+адмін\s+(\d+)", text_lower)
                if match:
                    try:
                        requested_level = int(match.group(1))
                        if requested_level > 4:
                            await message.reply("Максимальний рівень - 4. Рівень 5 недоступний для призначення.", parse_mode="html")
                            return
                    except ValueError:
                        pass
            await message.reply("Вкажи рівень: <code>+адмін 1</code>, <code>+адмін 2</code>, <code>+адмін 3</code>, <code>+адмін 4</code>.", parse_mode="html")
            return
        
        # Додаткова перевірка на всяк випадок (рівень не може бути > 4)
        if level > 4:
            await message.reply("Максимальний рівень - 4. Рівень 5 недоступний для призначення.", parse_mode="html")
            return
        
        # Перевірка, що не намагаються призначити рівень власнику бота
        if target_id in BOT_OWNER_IDS:
            await message.reply("Неможливо змінити рівень власника бота.", parse_mode="html")
            return
        
        ok_add, err_add = await _admin_promotion_allowed(
            bot, chat_id, user_id, target_id, is_remove=False, new_level=level
        )
        if not ok_add:
            await message.reply(err_add, parse_mode="html")
            return
        
        set_group_admin(chat_id, target_id, level, added_by=user_id)
        await message.reply(f"Адміністратора додано з рівнем {level}.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await message.reply(f"Помилка при обробці команди: {e}")
        except Exception:
            pass


# Відповідь на саме одне слово «Мафія» у групі (останнім, щоб не перехоплювати ХтоАдмін і +адмін)
@router_group_admin.message(
    F.chat.type.in_(GROUP_TYPES),
    F.text,
    F.func(_is_exact_mafia_word),
)
async def mafia_ack_reply(message: Message):
    reply = random.choice(MAFIA_ACK_REPLIES)
    await message.reply(emoji_to_premium(reply), parse_mode="html")


# Надійний варіант для груп: /адмін або /admin (бо звичайний текст +адмін може не доходити через Privacy Mode)
@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("адмін", "admin"))
async def cmd_admin_manage(message: Message, bot: Bot):
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id

        if not await _can_manage_admins(bot, chat_id, user_id):
            await message.reply(
                "Керувати адмінами можуть власник групи, адмін 4 рівня або старший адміністратор (рівень 3). "
                "Рівень 3 — лише <code>/адмін add 1</code>, <code>add 2</code> та зняття адмінів 1–2 рівня.",
                parse_mode="html",
            )
            return

        is_remove, level = _parse_slash_admin_args(message.text or "")
        target_id = await _resolve_target_user(message, bot)
        if not target_id:
            await message.reply(
                "Використання: reply на повідомлення користувача.\n"
                "Приклад: <code>/адмін add 3</code> або <code>/адмін del</code>",
                parse_mode="html",
            )
            return

        if target_id in BOT_OWNER_IDS:
            await message.reply("Неможливо змінити рівень власника бота.", parse_mode="html")
            return

        if is_remove:
            if get_group_admin_level(chat_id, target_id) == 0:
                await message.reply("Цей користувач не є адміном бота в цій групі.")
                return
            ok_rm, err_rm = await _admin_promotion_allowed(
                bot, chat_id, user_id, target_id, is_remove=True
            )
            if not ok_rm:
                await message.reply(err_rm, parse_mode="html")
                return
            remove_group_admin(chat_id, target_id)
            await message.reply(" Права адміна знято.")
            return

        if level is None:
            await message.reply(
                "Вкажи рівень: <code>/адмін add 1</code>, <code>/адмін add 2</code>, <code>/адмін add 3</code>, <code>/адмін add 4</code>.",
                parse_mode="html",
            )
            return

        ok_add, err_add = await _admin_promotion_allowed(
            bot, chat_id, user_id, target_id, is_remove=False, new_level=level
        )
        if not ok_add:
            await message.reply(err_add, parse_mode="html")
            return

        set_group_admin(chat_id, target_id, level, added_by=user_id)
        level_desc = {1: "мут", 2: "бан", 3: "налаштування групи (construct_event)", 4: "співвласник"}
        await message.reply(f" Адміна додано з рівнем {level} ({level_desc.get(level, '')}).")
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await message.reply(f"Помилка: {e}")
        except Exception:
            pass


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("settings", "chat_settings"))
async def cmd_chat_settings(message: Message, bot: Bot):
    """
    Відкрити налаштування цієї групи в ПП (конструктор ролей).
    Користувачу в особисті повідомлення відправляється кнопка, яка відкриває конструктор
    саме для цього чату.
    """
    if not message.from_user:
        return

    # Видаляємо повідомлення з командою /settings
    try:
        await message.delete()
    except Exception:
        pass

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Доступ тільки для адмінів 3 рівня і вище (construct_event)
    if not await _has_permission(bot, chat_id, user_id, ADMIN_LEVEL_CONSTRUCT):
        await message.reply(
            "Ти не можеш відкривати налаштування цієї групи.\n",
            parse_mode="html",
        )
        return
    construct = get_active_construct_event()
    if not construct:
        await message.reply("Конструктор тимчасово недоступний.")
        return

    ok = await construct.open_group_settings_direct(bot=bot, user_id=user_id, chat_id=chat_id)
    if not ok:
        await message.reply(
            "Я не зміг написати тобі в ПП.\n"
            "Будь ласка, спочатку напиши мені в особисті повідомлення /start, а потім повтори команду /settings.",
            parse_mode="html",
        )


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("silence_dead_on"))
async def cmd_silence_dead_on(message: Message, bot: Bot):
    if not message.from_user:
        return
    chat_id = message.chat.id
    if not await _has_permission(bot, chat_id, message.from_user.id, ADMIN_LEVEL_CONSTRUCT):
        await message.reply("Недостатньо прав.")
        return
    _set_group_theme_flag(chat_id, "silence_dead_players_enabled", True)
    await message.reply(" Мовчанку для мертвих увімкнено.")


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("silence_dead_off"))
async def cmd_silence_dead_off(message: Message, bot: Bot):
    if not message.from_user:
        return
    chat_id = message.chat.id
    if not await _has_permission(bot, chat_id, message.from_user.id, ADMIN_LEVEL_CONSTRUCT):
        await message.reply("Недостатньо прав.")
        return
    _set_group_theme_flag(chat_id, "silence_dead_players_enabled", False)
    await message.reply(" Мовчанку для мертвих вимкнено.")


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("silence_non_players_on"))
async def cmd_silence_non_players_on(message: Message, bot: Bot):
    if not message.from_user:
        return
    chat_id = message.chat.id
    if not await _has_permission(bot, chat_id, message.from_user.id, ADMIN_LEVEL_CONSTRUCT):
        await message.reply("Недостатньо прав.")
        return
    _set_group_theme_flag(chat_id, "silence_non_players_enabled", True)
    await message.reply(" Мовчанку для не-гравців увімкнено.")


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("silence_non_players_off"))
async def cmd_silence_non_players_off(message: Message, bot: Bot):
    if not message.from_user:
        return
    chat_id = message.chat.id
    if not await _has_permission(bot, chat_id, message.from_user.id, ADMIN_LEVEL_CONSTRUCT):
        await message.reply("Недостатньо прав.")
        return
    _set_group_theme_flag(chat_id, "silence_non_players_enabled", False)
    await message.reply(" Мовчанку для не-гравців вимкнено.")

# Фільтр для тексту БЕЗ команд (щоб не перехоплювати інші команди)
def _is_not_command(message: Message) -> bool:
    """Перевірка, що це не команда (не починається з /) і не +адмін/-адмін."""
    if not message.text:
        return False
    text = message.text.strip()
    # Пропускаємо команди, що починаються з /
    if text.startswith("/"):
        return False
    # Пропускаємо команди +адмін/-адмін - вони обробляються окремим handler
    text_lower = text.lower()
    if text_lower.startswith("+адмін") or text_lower.startswith("-адмін"):
        return False
    return True

# Текст «ХтоАдмін» вже обробляється text_hto_admin_handler. Інший текст у групі не перехоплюємо,
# щоб під час гри play міг видаляти повідомлення не-гравців і мутити їх.

@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("mute"))
async def cmd_mute(message: Message, bot: Bot):
    """Мут користувача: /мут [reply|@mention|user_id] [час] [причина]."""
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await _has_permission(bot, chat_id, user_id, ADMIN_LEVEL_MUTE):
        await message.reply("У тебе немає права мутити.")
        return

    target_id = await _resolve_target_user_with_id_fallback(message, bot)
    if not target_id:
        await message.reply(
            " Вкажи ціль: reply, @mention або user_id.\n"
            "Приклад: <code>/мут 123456789 30m флуд</code>",
            parse_mode="html",
        )
        return

    if await _is_admin_immune(bot, chat_id, target_id):
        await message.reply(" Цього користувача не можна замутити (адмін/власник).")
        return

    text = (message.text or "").strip()
    args = text.split(maxsplit=2)
    tail = args[2] if len(args) >= 3 else (args[1] if len(args) >= 2 and str(target_id) not in args[1] else "")
    mute_seconds, reason = _parse_mute_duration(tail)
    if mute_seconds is None:
        mute_seconds = 30 * 60

    until = datetime.utcnow() + timedelta(seconds=mute_seconds)
    try:
        await bot.restrict_chat_member(
            chat_id,
            target_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        reason_text = f"\nПричина: {reason}" if reason else ""
        await message.reply(f"🔇 Користувача замучено на {mute_seconds} с.{reason_text}")
    except Exception as e:
        await message.reply(f" Помилка муту: {e}")


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("warn"))
async def cmd_warn(message: Message, bot: Bot):
    """
    Warn користувача:
    /warn [reply|@mention|user_id] [причина]
    Ліміт: 5/5. На 5-му warn -> автомут на 1 годину.
    """
    if not message.from_user:
        return
    chat_id = message.chat.id
    actor_id = message.from_user.id
    if not await _has_permission(bot, chat_id, actor_id, ADMIN_LEVEL_MUTE):
        await message.reply("У тебе немає права видавати warn.")
        return

    target_id = await _resolve_target_user_with_id_fallback(message, bot)
    if not target_id:
        await message.reply(
            "Вкажи ціль: reply, @mention або user_id.\n"
            "Приклад: <code>/warn 123456789 spam</code>",
            parse_mode="html",
        )
        return

    if await _is_admin_immune(bot, chat_id, target_id):
        actor_level = await _get_effective_admin_level(bot, chat_id, actor_id)
        target_level = await _get_effective_admin_level(bot, chat_id, target_id)
        target_db_level = get_group_admin_level(chat_id, target_id)

        # Дозволяємо warn по адміну лише якщо ініціатор має СТРОГО вищий рівень.
        # Для Telegram-адмінів без рівня в БД (target_db_level == 0) лишаємо імунітет.
        can_warn_lower_admin = (
            actor_level > target_level
            and (
                target_db_level >= ADMIN_LEVEL_MUTE
                or target_level in (ADMIN_LEVEL_COOWNER, ADMIN_LEVEL_BOT_OWNER)
            )
        )
        if not can_warn_lower_admin:
            await message.reply("Цьому користувачу не можна видати warn (адмін/власник).")
            return

    raw = (message.text or "").strip()
    parts = raw.split(maxsplit=2)
    reason = ""
    if len(parts) >= 3:
        reason = parts[2].strip()
    elif len(parts) >= 2 and str(target_id) not in parts[1]:
        reason = parts[1].strip()

    warns = _increment_warns(chat_id, target_id)
    reason_text = f"\nReason: {reason}" if reason else ""

    if warns >= MAX_WARNS:
        until = datetime.utcnow() + timedelta(seconds=WARN_AUTO_MUTE_SECONDS)
        try:
            await bot.restrict_chat_member(
                chat_id,
                target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            await message.reply(
                f"Warn issued: <code>{warns}/{MAX_WARNS}</code>{reason_text}\n"
                f"🔇 Auto-mute for {WARN_AUTO_MUTE_SECONDS // 3600}h.",
                parse_mode="html",
            )
        except Exception as e:
            await message.reply(
                f"Warn issued: <code>{warns}/{MAX_WARNS}</code>{reason_text}\n"
                f" Auto-mute failed: {e}",
                parse_mode="html",
            )
        return

    await message.reply(
        f"Warn issued: <code>{warns}/{MAX_WARNS}</code>{reason_text}",
        parse_mode="html",
    )


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("unwarn", "delwarn", "знятиварн"))
async def cmd_unwarn(message: Message, bot: Bot):
    """
    Зняти warn(и) користувачу:
    /unwarn [reply|@mention|user_id] [кількість|all]
    За замовчуванням знімає 1 warn. `all` або `0` — обнулити всі.
    Якщо лічильник опускається нижче ліміту — знімаємо авто-мут.
    """
    if not message.from_user:
        return
    chat_id = message.chat.id
    actor_id = message.from_user.id
    if not await _has_permission(bot, chat_id, actor_id, ADMIN_LEVEL_MUTE):
        await message.reply("У тебе немає права знімати warn.")
        return

    target_id = await _resolve_target_user_with_id_fallback(message, bot)
    if not target_id:
        await message.reply(
            "Вкажи ціль: reply, @mention або user_id.\n"
            "Приклади: <code>/unwarn 123456789</code>, <code>/unwarn @user all</code>",
            parse_mode="html",
        )
        return

    # Розбираємо аргумент кількості (необов'язковий)
    raw = (message.text or "").strip()
    parts = raw.split()
    clear_all = False
    by = 1
    for tok in parts[1:]:
        low = tok.lower()
        if low in ("all", "всі", "усі", "clear", "0"):
            clear_all = True
            break
        if low.isdigit():
            by = int(low)

    before = _get_warns_count(chat_id, target_id)
    if before <= 0:
        await message.reply("У користувача немає активних warn.")
        return

    if clear_all:
        warns = _set_warns_count(chat_id, target_id, 0)
    else:
        warns = _decrement_warns(chat_id, target_id, by)

    # Якщо опустилися нижче ліміту — знімаємо авто-мут (best-effort).
    unmuted_note = ""
    if before >= MAX_WARNS and warns < MAX_WARNS:
        try:
            await bot.restrict_chat_member(chat_id, target_id, permissions=FULL_PERMISSIONS)
            unmuted_note = "\n🔊 Авто-мут знято."
        except Exception:
            pass

    await message.reply(
        f"Warn знято: <code>{warns}/{MAX_WARNS}</code>{unmuted_note}",
        parse_mode="html",
    )


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot):
    """Зняти мут (рівень 1+)."""
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await _has_permission(bot, chat_id, user_id, ADMIN_LEVEL_MUTE):
        await message.reply("У тебе немає права знімати мут.")
        return

    target_id = await _resolve_target_user_with_id_fallback(message, bot)
    if not target_id:
        await message.reply("Вкажи ціль: reply, @mention або user_id.")
        return

    try:
        await bot.restrict_chat_member(
            chat_id,
            target_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await message.reply("🔊 Мут знято.")
    except Exception as e:
        await message.reply(f"Помилка: {e}")


FULL_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("unmute_all", "розмутити_всіх"))
async def cmd_unmute_all(message: Message, bot: Bot):
    """Розмутити всіх, кого бот замутив під час гри (не гравці писали в чат)."""
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await _has_permission(bot, chat_id, user_id, ADMIN_LEVEL_MUTE):
        await message.reply("У тебе немає права знімати мут.")
        return

    state = game_state_manager.get_state(chat_id)
    to_unmute = list(state.muted_during_game)
    state.muted_during_game.clear()

    if not to_unmute:
        await message.reply("🔊 Нікого з замучених під час гри немає.")
        return

    done = 0
    for uid in to_unmute:
        try:
            await bot.restrict_chat_member(
                chat_id,
                uid,
                permissions=FULL_PERMISSIONS,
            )
            done += 1
        except Exception:
            pass
    await message.reply(f"🔊 Розмучено {done} з {len(to_unmute)}.")


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    """
    Бан користувача:
    /бан [reply|@mention|user_id] [час] [причина]
    Час: s,m,h,d,mo,y. Без часу -> назавжди.
    """
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await _has_permission(bot, chat_id, user_id, ADMIN_LEVEL_BAN):
        await message.reply(" У тебе немає права банити.")
        return

    target_id = await _resolve_target_user_with_id_fallback(message, bot)
    if not target_id:
        await message.reply(
            " Вкажи ціль: reply, @mention або user_id.\n"
            "Приклад: <code>/бан 123456789 7d токсичність</code>\n"
            "Або без часу: <code>/бан 123456789 спам</code> (назавжди).",
            parse_mode="html",
        )
        return

    if await _is_admin_immune(bot, chat_id, target_id):
        await message.reply(" Цього користувача не можна забанити (адмін/власник).")
        return

    raw = (message.text or "").strip()
    parts = raw.split(maxsplit=2)
    tail = ""
    if len(parts) >= 3:
        tail = parts[2]
    elif len(parts) >= 2 and str(target_id) not in parts[1]:
        tail = parts[1]
    ban_seconds, reason = _parse_ban_duration_and_reason(tail)

    try:
        if ban_seconds is None:
            await bot.ban_chat_member(chat_id, target_id)
            reason_text = f"\nПричина: {reason}" if reason else ""
            await message.reply(f"Користувача забанено назавжди.{reason_text}")
        else:
            until = datetime.utcnow() + timedelta(seconds=ban_seconds)
            await bot.ban_chat_member(chat_id, target_id, until_date=until)
            reason_text = f"\nПричина: {reason}" if reason else ""
            await message.reply(f"Користувача забанено на {ban_seconds} с.{reason_text}")
    except Exception as e:
        await message.reply(f" Помилка бану: {e}")


@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    """Розбан: /розбан [reply|@mention|user_id]."""
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await _has_permission(bot, chat_id, user_id, ADMIN_LEVEL_BAN):
        await message.reply(" У тебе немає права розбанювати.")
        return

    target_id = await _resolve_target_user_with_id_fallback(message, bot)
    if not target_id:
        await message.reply(
            " Вкажи ціль: reply, @mention або user_id.\n"
            "Приклад: <code>/розбан 123456789</code>",
            parse_mode="html",
        )
        return

    try:
        await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        await message.reply("Користувача розбанено.")
    except Exception as e:
        await message.reply(f" Помилка розбану: {e}")


def _user_display_name(user) -> str:
    """Ім'я для відображення: ім'я або @username або ID."""
    if not user:
        return "?"
    name = (getattr(user, "first_name", "") or "").strip()
    if getattr(user, "last_name", None):
        name = f"{name} {user.last_name}".strip()
    if not name:
        name = getattr(user, "username", None) or ""
    if name and not name.startswith("@"):
        name = name[:30]
    if getattr(user, "username", None):
        name = f"{name} (@{user.username})" if name else f"@{user.username}"
    if not name:
        name = f"ID {getattr(user, 'id', '?')}"
    return name or f"ID {getattr(user, 'id', '?')}"


async def _reply_admin_list(chat_id: int, bot: Bot, message: Message) -> None:
    """Відправляє меню категорій адмінів з кнопками."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👑 Власниця", callback_data=f"adminlist:{chat_id}:owner")],
            [InlineKeyboardButton(text="4 - Співвласники", callback_data=f"adminlist:{chat_id}:l4")],
            [InlineKeyboardButton(text="3 - Старші адміністратори", callback_data=f"adminlist:{chat_id}:l3")],
            [InlineKeyboardButton(text="2 - Адміністратори", callback_data=f"adminlist:{chat_id}:l2")],
            [InlineKeyboardButton(text="1 - Стажери", callback_data=f"adminlist:{chat_id}:l1")],
            [InlineKeyboardButton(text="Закрити", callback_data=f"adminlist:{chat_id}:close")],
        ]
    )
    await message.reply(
        "👑 <b>Усі адміни групи</b>\n\nОбери категорію кнопкою нижче:",
        parse_mode="html",
        reply_markup=kb,
    )


async def _build_admin_section_text(chat_id: int, bot: Bot, section: str) -> str:
    """Будує текст для обраної категорії адмінів."""
    admins = await bot.get_chat_administrators(chat_id)
    rows = get_group_admins_list(chat_id)
    bot_level_by_uid = {uid: lvl for uid, lvl in rows}
    
    # Групуємо адмінів по рівнях
    admins_by_level = {1: [], 2: [], 3: [], 4: [], 5: []}
    creator = None
    
    for a in admins:
        if a.status == ChatMemberStatus.CREATOR:
            creator = a
            continue
        
        if a.status == ChatMemberStatus.ADMINISTRATOR:
            lvl = bot_level_by_uid.get(a.user.id)
            if lvl and lvl in admins_by_level:
                admins_by_level[lvl].append(a)

    if section == "owner":
        if creator:
            name = _user_display_name(creator.user)
            return f"👑 <b>Власниця</b>\n\n{name}"
        return "👑 <b>Власниця</b>\n\nНемає даних."

    level_map = {
        "l4": (4, "4 - Співвласники"),
        "l3": (3, "3 - Старші адміністратори"),
        "l2": (2, "2 - Адміністратори"),
        "l1": (1, "1 - Стажери"),
    }
    if section not in level_map:
        return "Невідома категорія."

    level, title = level_map[section]
    members = admins_by_level.get(level, [])
    lines = [f"📋 <b>{title}</b>", ""]
    if not members:
        lines.append("Немає адмінів у цій категорії.")
    else:
        for a in members:
            lines.append(f"• {_user_display_name(a.user)}")
    return "\n".join(lines)


def _admin_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👑 Власниця", callback_data=f"adminlist:{chat_id}:owner")],
            [InlineKeyboardButton(text="4 - Співвласники", callback_data=f"adminlist:{chat_id}:l4")],
            [InlineKeyboardButton(text="3 - Старші адміністратори", callback_data=f"adminlist:{chat_id}:l3")],
            [InlineKeyboardButton(text="2 - Адміністратори", callback_data=f"adminlist:{chat_id}:l2")],
            [InlineKeyboardButton(text="1 - Стажери", callback_data=f"adminlist:{chat_id}:l1")],
            [InlineKeyboardButton(text=" Закрити", callback_data=f"adminlist:{chat_id}:close")],
        ]
    )


def _admin_back_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adminlist:{chat_id}:menu")],
            [InlineKeyboardButton(text=" Закрити", callback_data=f"adminlist:{chat_id}:close")],
        ]
    )


@router_group_admin.callback_query(F.data.startswith("adminlist:"))
async def adminlist_callback(callback: CallbackQuery, bot: Bot):
    data = callback.data or ""
    parts = data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        chat_id = int(parts[1])
    except Exception:
        await callback.answer()
        return
    action = parts[2]

    if action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        return

    if action == "menu":
        try:
            await callback.message.edit_text(
                "👑 <b>Усі адміни групи</b>\n\nОбери категорію кнопкою нижче:",
                parse_mode="html",
                reply_markup=_admin_menu_keyboard(chat_id),
            )
        except Exception:
            pass
        await callback.answer()
        return

    text = await _build_admin_section_text(chat_id, bot, action)
    try:
        await callback.message.edit_text(
            text,
            parse_mode="html",
            reply_markup=_admin_back_keyboard(chat_id),
        )
    except Exception:
        pass
    await callback.answer()


def _is_hto_admin_text(text: str) -> bool:
    """Чи повідомлення - це «ХтоАдмін» (регістр і пробіли не враховуються)."""
    if not text:
        return False
    t = text.strip().lower().replace(" ", "").replace("_", "").replace("-", "").replace(".", "")
    variants = ("хтоадмін", "хтоадмин", "хтоадмiн")
    return t in variants or t.startswith("хтоадм")


# Handler для команди /адміни через Command filter
# Fallback handler для /адміни (якщо Command filter не спрацював)
@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), F.text, F.func(_is_admins_command))
async def cmd_list_admins_fallback(message: Message, bot: Bot):
    """Fallback для команди /адміни (якщо Command filter не спрацював)."""
    try:
        await _reply_admin_list(message.chat.id, bot, message)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await message.reply(f"Помилка: {e}")
        except Exception:
            pass

@router_group_admin.message(F.chat.type.in_(GROUP_TYPES), Command("адміни", "admins", "хто_адмін", "хто_админ"))
async def cmd_list_admins(message: Message, bot: Bot):
    """Список усіх адмінів по команді /хто_адмін або /адміни."""
    try:
        await _reply_admin_list(message.chat.id, bot, message)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await message.reply(f"Помилка: {e}")
        except Exception:
            pass




