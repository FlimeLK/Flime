import asyncio
import random
import unicodedata
from datetime import datetime, date, timedelta
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.database import cursor, conn, get_balance, deduct_balance, add_balance_to_user
from commands.buff_shop import ITEMS
from premium_emoji import CUSTOM_EMOJI_MAP, custom_emoji_id_for_symbol, emoji_to_premium

router_egg = Router()


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_execute(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0

# Локальні ID (дубль premium_emoji.py): якщо на сервері застарілий premium_emoji без цих ключів -
# кнопки та /egg все одно отримають преміум-емодзі.
_EGG_PREMIUM_IDS: dict[str, str] = {
    "🥚": "5343930500186674098",
    "🐣": "5341496280227028271",
    "💡": "5341465468131646647",
    "🧪": "5341644898980370960",
    "🧼": "5341597302152796852",
}

BOT_OWNER_ID = 1859870653
EGG_OPEN_MONTH = 4
EGG_OPEN_DAY = 12

LAMP_COST = 10
INCUBATOR_COST = 20
FEED_COST = 6
CLEAN_COST = 4

FEED_COOLDOWN = timedelta(hours=2)
CLEAN_COOLDOWN = timedelta(hours=2)


def _egg_emoji_mapping() -> dict[str, str]:
    return {**CUSTOM_EMOJI_MAP, **_EGG_PREMIUM_IDS}


def _egg_custom_emoji_id(symbol: str) -> str | None:
    n = unicodedata.normalize("NFC", symbol)
    if n in _EGG_PREMIUM_IDS:
        return _EGG_PREMIUM_IDS[n]
    return custom_emoji_id_for_symbol(symbol)


def _egg_premium_html(text: str) -> str:
    """Преміум-емодзі: глобальна мапа + обов'язкові ID для івенту яйця."""
    return emoji_to_premium(text or "", mapping=_egg_emoji_mapping())


def _egg_icon_button(label: str, callback_data: str, icon_symbol: str) -> InlineKeyboardButton:
    cid = _egg_custom_emoji_id(icon_symbol)
    if cid:
        return InlineKeyboardButton(
            text=label,
            callback_data=callback_data,
            icon_custom_emoji_id=cid,
        )
    return InlineKeyboardButton(text=f"{icon_symbol} {label}", callback_data=callback_data)


def _main_kb_plain() -> InlineKeyboardMarkup:
    """Клавіатура без icon_custom_emoji_id - якщо API/клієнт відхиляє іконки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"💡 Лампа - {LAMP_COST}💵", callback_data="egg:lamp"),
                InlineKeyboardButton(text=f"🧪 Інкубатор - {INCUBATOR_COST}💵", callback_data="egg:incubator"),
            ],
            [
                InlineKeyboardButton(text=f"🍞 Корм - {FEED_COST}💵", callback_data="egg:feed"),
                InlineKeyboardButton(text=f"🧼 Чистка - {CLEAN_COST}💵", callback_data="egg:clean"),
            ],
        ]
    )


async def _egg_try_answer(
    message: Message,
    raw_html: str,
    kb_primary: InlineKeyboardMarkup | None,
    kb_plain: InlineKeyboardMarkup | None = None,
) -> None:
    keyboards = (kb_primary, kb_plain) if kb_plain is not None else (kb_primary,)
    last_err: TelegramBadRequest | None = None
    for kb in keyboards:
        for txt in (_egg_premium_html(raw_html), raw_html):
            try:
                await message.answer(txt, reply_markup=kb, parse_mode="html")
                return
            except TelegramBadRequest as e:
                last_err = e
                continue
    if last_err is not None:
        raise last_err


async def _egg_answer_html(message: Message, raw_html: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    await _egg_try_answer(message, raw_html, reply_markup, None)


async def _egg_try_edit(
    message: Message,
    raw_html: str,
    kb_primary: InlineKeyboardMarkup | None,
    kb_plain: InlineKeyboardMarkup | None = None,
) -> None:
    """Преміум-текст → звичайний HTML; клавіатура з іконками → без icon_custom_emoji_id (якщо передано kb_plain)."""
    keyboards = (kb_primary, kb_plain) if kb_plain is not None else (kb_primary,)
    last_err: TelegramBadRequest | None = None
    for kb in keyboards:
        for txt in (_egg_premium_html(raw_html), raw_html):
            try:
                await message.edit_text(txt, reply_markup=kb, parse_mode="html")
                return
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
                last_err = e
                continue
    if last_err is not None:
        raise last_err


def _ensure_egg_schema() -> None:
    """Гарантує наявність колонок egg_event_state навіть без повного рестарту/міграцій."""
    try:
        _db_execute(
            """
            CREATE TABLE IF NOT EXISTS egg_event_state (
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                has_egg BOOLEAN NOT NULL DEFAULT FALSE,
                stage INTEGER NOT NULL DEFAULT 1,
                progress INTEGER NOT NULL DEFAULT 0,
                growth INTEGER NOT NULL DEFAULT 0,
                stability INTEGER NOT NULL DEFAULT 0,
                quality INTEGER NOT NULL DEFAULT 0,
                risk INTEGER NOT NULL DEFAULT 0,
                lamp_until TIMESTAMP,
                incubator_cooldown_until TIMESTAMP,
                lamp_uses INTEGER NOT NULL DEFAULT 0,
                incubator_uses INTEGER NOT NULL DEFAULT 0,
                feed_uses INTEGER NOT NULL DEFAULT 0,
                clean_uses INTEGER NOT NULL DEFAULT 0,
                overcare_percent INTEGER NOT NULL DEFAULT 0,
                feed_date DATE,
                feed_count INTEGER NOT NULL DEFAULT 0,
                clean_date DATE,
                clean_count INTEGER NOT NULL DEFAULT 0,
                opened BOOLEAN NOT NULL DEFAULT FALSE,
                result_type VARCHAR(32),
                opened_at TIMESTAMP,
                last_action_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                pending_hint TEXT,
                feed_cooldown_until TIMESTAMP,
                clean_cooldown_until TIMESTAMP
            )
            """
        )
        _db_execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'feed_uses'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN feed_uses INTEGER NOT NULL DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'clean_uses'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN clean_uses INTEGER NOT NULL DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'overcare_percent'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN overcare_percent INTEGER NOT NULL DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'last_action_at'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN last_action_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'pending_hint'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN pending_hint TEXT;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'feed_cooldown_until'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN feed_cooldown_until TIMESTAMP;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'clean_cooldown_until'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN clean_cooldown_until TIMESTAMP;
                END IF;
            END $$
            """
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _open_date_this_year() -> date:
    now = datetime.now()
    return date(now.year, EGG_OPEN_MONTH, EGG_OPEN_DAY)


def _dt_naive_local(dt) -> datetime | None:
    """Порівняння з datetime.now() без зсуву через timezone з PostgreSQL."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None):
        return dt.astimezone().replace(tzinfo=None)
    return dt.replace(tzinfo=None) if hasattr(dt, "replace") else dt


def _ensure_user_exists(user) -> None:
    if not user:
        return
    uid = int(user.id)
    tg_name = (getattr(user, "first_name", None) or "").strip() or None
    link = getattr(user, "username", None) or None
    row = _db_fetchone("SELECT 1 FROM users WHERE id = %s", (uid,))
    if row is None:
        _db_execute("INSERT INTO users (id, tg_name, link) VALUES (%s, %s, %s)", (uid, tg_name, link))
    else:
        _db_execute("UPDATE users SET tg_name = %s, link = %s WHERE id = %s", (tg_name, link, uid))
    conn.commit()


def _get_state(user_id: int):
    _ensure_egg_schema()
    row = _db_fetchone(
        """
        SELECT has_egg, stage, progress, growth, stability, quality, risk,
               lamp_until, incubator_cooldown_until, lamp_uses, incubator_uses, feed_uses, clean_uses, overcare_percent, feed_date, feed_count,
               clean_date, clean_count, opened, result_type, last_action_at, pending_hint,
               feed_cooldown_until, clean_cooldown_until
        FROM egg_event_state
        WHERE user_id = %s
        """,
        (user_id,),
    )
    if not row:
        return None
    return {
        "has_egg": bool(row[0]),
        "stage": int(row[1] or 1),
        "progress": int(row[2] or 0),
        "growth": int(row[3] or 0),
        "stability": int(row[4] or 0),
        "quality": int(row[5] or 0),
        "risk": int(row[6] or 0),
        "lamp_until": row[7],
        "incubator_cooldown_until": row[8],
        "lamp_uses": int(row[9] or 0),
        "incubator_uses": int(row[10] or 0),
        "feed_uses": int(row[11] or 0),
        "clean_uses": int(row[12] or 0),
        "overcare_percent": int(row[13] or 0),
        "feed_date": row[14],
        "feed_count": int(row[15] or 0),
        "clean_date": row[16],
        "clean_count": int(row[17] or 0),
        "opened": bool(row[18]),
        "result_type": row[19],
        "last_action_at": row[20],
        "pending_hint": row[21],
        "feed_cooldown_until": row[22],
        "clean_cooldown_until": row[23],
    }


def _upsert_state(user_id: int, s: dict) -> None:
    _ensure_egg_schema()
    _db_execute(
        """
        INSERT INTO egg_event_state (
            user_id, has_egg, stage, progress, growth, stability, quality, risk,
            lamp_until, incubator_cooldown_until, lamp_uses, incubator_uses, feed_uses, clean_uses, overcare_percent, feed_date, feed_count, clean_date, clean_count,
            opened, result_type, opened_at, last_action_at, feed_cooldown_until, clean_cooldown_until, pending_hint
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, CURRENT_TIMESTAMP, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            has_egg = EXCLUDED.has_egg,
            stage = EXCLUDED.stage,
            progress = EXCLUDED.progress,
            growth = EXCLUDED.growth,
            stability = EXCLUDED.stability,
            quality = EXCLUDED.quality,
            risk = EXCLUDED.risk,
            lamp_until = EXCLUDED.lamp_until,
            incubator_cooldown_until = EXCLUDED.incubator_cooldown_until,
            lamp_uses = EXCLUDED.lamp_uses,
            incubator_uses = EXCLUDED.incubator_uses,
            feed_uses = EXCLUDED.feed_uses,
            clean_uses = EXCLUDED.clean_uses,
            overcare_percent = EXCLUDED.overcare_percent,
            feed_date = EXCLUDED.feed_date,
            feed_count = EXCLUDED.feed_count,
            clean_date = EXCLUDED.clean_date,
            clean_count = EXCLUDED.clean_count,
            opened = EXCLUDED.opened,
            result_type = EXCLUDED.result_type,
            last_action_at = CURRENT_TIMESTAMP,
            feed_cooldown_until = EXCLUDED.feed_cooldown_until,
            clean_cooldown_until = EXCLUDED.clean_cooldown_until,
            pending_hint = EXCLUDED.pending_hint
        """,
        (
            user_id, s["has_egg"], s["stage"], s["progress"], s["growth"], s["stability"], s["quality"], s["risk"],
            s["lamp_until"], s["incubator_cooldown_until"], s["lamp_uses"], s["incubator_uses"], s["feed_uses"], s["clean_uses"], s["overcare_percent"], s["feed_date"], s["feed_count"], s["clean_date"], s["clean_count"],
            s["opened"], s.get("result_type"), s.get("feed_cooldown_until"), s.get("clean_cooldown_until"), s.get("pending_hint"),
        ),
    )
    conn.commit()


def _stage_from_progress(progress: int) -> int:
    if progress >= 85:
        return 5
    if progress >= 60:
        return 4
    if progress >= 40:
        return 3
    if progress >= 20:
        return 2
    return 1


def _had_any_care_interaction(s: dict) -> bool:
    """Будь-яка з 4 дій догляду (лампа, інкубатор, корм, чистка) хоча б раз."""
    return (
        int(s.get("lamp_uses", 0)) > 0
        or int(s.get("incubator_uses", 0)) > 0
        or int(s.get("feed_uses", 0)) > 0
        or int(s.get("clean_uses", 0)) > 0
    )


def _stage_text_for_state(s: dict) -> str:
    """Рядок настрою стадії; «Холодне і тихе.» лише після першої взаємодії (догляд)."""
    stage = int(s.get("stage", 1) or 1)
    by_stage = {
        1: "Холодне і тихе.",
        2: "З'явились тріщини.",
        3: "Тепле. Реагує.",
        4: "Всередині щось рухається.",
        5: "Майже вилупилось.",
    }
    line = by_stage.get(stage, by_stage[1])
    if stage == 1 and not _had_any_care_interaction(s):
        return ""
    return line


def _care_all_four_done(s: dict) -> bool:
    """Чи зроблено кожну з 4 дій догляду хоча б раз (лампа, інкубатор, корм, чистка)."""
    return (
        int(s.get("lamp_uses", 0)) >= 1
        and int(s.get("incubator_uses", 0)) >= 1
        and int(s.get("feed_uses", 0)) >= 1
        and int(s.get("clean_uses", 0)) >= 1
    )


def _dynamic_state_line(s: dict) -> str:
    """✨/🔥/🌫 лише після повного циклу догляду (усі 4 дії ≥1 раз); до того - без рядка."""
    if not _care_all_four_done(s):
        return ""
    r, q, st = int(s["risk"]), int(s["quality"]), int(s["stability"])
    if r >= 60:
        return "🌫 Щось не так.\nТи це відчуваєш."
    if q >= 60:
        return "🔥 Воно реагує на тебе.\nЦе хороший знак."
    if st >= 50:
        return "✨ Все йде рівно."
    return random.choice(
        (
            "✨ Все йде рівно.",
            "✨ Все йде як треба.",
        )
    )


def _progress_bar(value: int, max_value: int = 100, slots: int = 5) -> str:
    ratio = max(0.0, min(1.0, value / max_value))
    filled = int(round(ratio * slots))
    return "█" * filled + "░" * (slots - filled)


def _fmt_remaining(until_dt) -> str:
    if not until_dt:
        return "готово"
    now = datetime.now().replace(tzinfo=None)
    until_naive = _dt_naive_local(until_dt)
    if not until_naive:
        return "готово"
    left = (until_naive - now).total_seconds()
    if left <= 0:
        return "готово"
    h = int(left // 3600)
    m = int((left % 3600) // 60)
    if h > 0:
        return f"{h}г {m}хв"
    return f"{m}хв"


def _main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _egg_icon_button(f"Лампа - {LAMP_COST}💵", "egg:lamp", "💡"),
                _egg_icon_button(f"Інкубатор - {INCUBATOR_COST}💵", "egg:incubator", "🧪"),
            ],
            [
                _egg_icon_button(f"Корм - {FEED_COST}💵", "egg:feed", "🍞"),
                _egg_icon_button(f"Чистка - {CLEAN_COST}💵", "egg:clean", "🧼"),
            ],
        ]
    )


def _first_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_egg_icon_button("Взяти яйце", "egg:claim", "🥚")]]
    )


def _first_kb_plain() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🥚 Взяти яйце", callback_data="egg:claim")]]
    )


def _open_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_egg_icon_button("Відкрити яйце", "egg:open", "🐣")]]
    )


def _open_kb_plain() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🐣 Відкрити яйце", callback_data="egg:open")]]
    )


_PENDING_AFTER_ACTION: dict[str, str] = {
    "lamp": "🥚\nВоно тепліше, ніж було раніше.",
    "incubator": "🥚\nВоно росте стабільно.\nЦе хороший знак.",
    "feed": "🥚\nЩось змінилось.\nІ це добре.",
    "clean": "🥚\nВоно виглядає стабільніше.",
}


def _main_text(
    s: dict,
    *,
    action_feedback: str = "",
    show_pending_hint: bool = True,
) -> str:
    """Порядок: заголовок → стадія/прогрес → опис стадії → (pending) → динаміка → (текст дії)."""
    stage_line = _stage_text_for_state(s)
    head = (
        "🥚 <b>Яйце</b>\n"
        f"Стадія: <b>{s['stage']}/5</b>\n"
        f"Прогрес: <b>{max(0, min(100, s['progress']))}%</b>"
        + (f"\n\n{stage_line}" if stage_line else "")
    )
    parts: list[str] = [head]
    if show_pending_hint and s.get("pending_hint"):
        parts.append(str(s["pending_hint"]).strip())
    dyn = _dynamic_state_line(s)
    if dyn:
        parts.append(dyn)
    body = "\n\n".join(parts)
    if action_feedback.strip():
        body += "\n\n" + action_feedback.strip()
    return body


def _clear_pending_hint_db(user_id: int) -> None:
    try:
        _db_execute(
            "UPDATE egg_event_state SET pending_hint = NULL WHERE user_id = %s AND pending_hint IS NOT NULL",
            (user_id,),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _egg_panel_raw_html(
    user_id: int,
    s: dict,
    *,
    action_feedback: str = "",
    consume_pending: bool,
) -> str:
    """HTML основного екрану без tg-emoji (для fallback при відхиленні Telegram)."""
    body = _main_text(
        s,
        action_feedback=action_feedback,
        show_pending_hint=consume_pending,
    )
    if consume_pending and s.get("pending_hint"):
        _clear_pending_hint_db(user_id)
        s["pending_hint"] = None
    return body


def _can_open_today(user_id: int) -> bool:
    return datetime.now().date() >= _open_date_this_year()


def _grant_rare_buff(user_id: int) -> str | None:
    preferred = ["black_hole", "capone_hat", "flashlight", "smoke_grenade", "lucky_cat"]
    buff_id = next((bid for bid in preferred if bid in ITEMS), None)
    if not buff_id and ITEMS:
        buff_id = list(ITEMS.keys())[0]
    if not buff_id:
        return None
    item = ITEMS[buff_id]
    _db_execute(
        """
        INSERT INTO user_buffs (user_id, buff_id, buff_name, quantity, infinite, is_unique)
        VALUES (%s, %s, %s, 1, FALSE, FALSE)
        ON CONFLICT (user_id, buff_id) DO UPDATE SET quantity = COALESCE(user_buffs.quantity, 0) + 1
        """,
        (user_id, buff_id, item.name),
    )
    conn.commit()
    return item.name


@router_egg.message(Command("egg"))
async def egg_cmd(message: Message):
    if message.chat.type != "private":
        await message.answer(
            _egg_premium_html("🥚 Команда працює в особистих повідомленнях з ботом."),
            parse_mode="html",
        )
        return
    if not message.from_user:
        return
    _ensure_user_exists(message.from_user)
    uid = int(message.from_user.id)
    s = _get_state(uid)
    if not s or not s["has_egg"]:
        await _egg_try_answer(
            message,
            "🥚\n"
            "Тобі передали яйце.\n"
            "Без пояснень.\n"
            "Без імені.\n"
            "Кажуть - відкриється 12 квітня.",
            _first_kb(),
            _first_kb_plain(),
        )
        return
    if s["opened"]:
        await message.answer(
            _egg_premium_html(
                "📊\n"
                f"Твоє яйце:\n"
                f"Ріст: {_progress_bar(s['growth'])}\n"
                f"Стабільність: {_progress_bar(s['stability'])}\n"
                f"Якість: {_progress_bar(s['quality'])}\n"
                f"Ризик: {_progress_bar(s['risk'])}"
            ),
            parse_mode="html",
        )
        return
    if _can_open_today(uid):
        await _egg_try_answer(
            message,
            "🐣\n"
            "Сьогодні.\n"
            "Більше нічого змінити не можна.",
            _open_kb(),
            _open_kb_plain(),
        )
        return
    raw_panel = _egg_panel_raw_html(uid, s, consume_pending=True)
    await _egg_try_answer(message, raw_panel, _main_kb(), _main_kb_plain())


@router_egg.callback_query(F.data == "egg:claim")
async def egg_claim(callback: CallbackQuery):
    if not callback.from_user:
        return await callback.answer()
    uid = int(callback.from_user.id)
    s = _get_state(uid) or {
        "has_egg": False, "stage": 1, "progress": 0, "growth": 0, "stability": 0, "quality": 0, "risk": 0,
        "lamp_until": None, "incubator_cooldown_until": None, "lamp_uses": 0, "incubator_uses": 0, "feed_uses": 0, "clean_uses": 0, "overcare_percent": 0, "feed_date": None, "feed_count": 0,
        "clean_date": None, "clean_count": 0, "opened": False, "result_type": None,
        "pending_hint": None, "feed_cooldown_until": None, "clean_cooldown_until": None,
    }
    s["has_egg"] = True
    _upsert_state(uid, s)
    try:
        await _egg_try_edit(
            callback.message,
            "🥚\nТепер воно твоє.\nНе впусти момент.\n\n<i>Основний екран і догляд - команда</i> /egg",
            None,
            None,
        )
    except Exception:
        try:
            await _egg_answer_html(
                callback.message,
                "🥚\nТепер воно твоє.\nНе впусти момент.\n\nОсновний екран і догляд - /egg",
            )
        except Exception:
            pass
    await callback.answer("Взято.")


async def _apply_action(callback: CallbackQuery, action: str):
    try:
        if not callback.from_user or not callback.message:
            return await callback.answer()
        uid = int(callback.from_user.id)
        s = _get_state(uid)
        if not s or not s["has_egg"]:
            await callback.answer("Спершу /egg і «Взяти яйце».", show_alert=True)
            return
        if s["opened"]:
            await callback.answer("Яйце вже відкрите.", show_alert=True)
            return
        if _can_open_today(uid):
            try:
                await _egg_try_edit(
                    callback.message,
                    "🐣\nСьогодні.\nБільше нічого змінити не можна.",
                    _open_kb(),
                    _open_kb_plain(),
                )
            except Exception:
                pass
            await callback.answer()
            return

        now = datetime.now().replace(tzinfo=None)
        today = now.date()
        cb_msg: str | None = None
        cb_alert = False
        pending_override: str | None = None

        if action == "lamp":
            lu = _dt_naive_local(s.get("lamp_until"))
            if lu and lu > now:
                cd_text = _fmt_remaining(s["lamp_until"])
                await callback.answer(
                    f"⏱️ Лампа\nЩе залишилося {cd_text}.",
                    show_alert=True,
                )
                return
            if not deduct_balance(uid, LAMP_COST):
                await callback.answer("Недостатньо 💵.", show_alert=True)
                return
            s["growth"] += 8
            s["risk"] += 5
            s["progress"] += 1
            s["lamp_uses"] = int(s.get("lamp_uses", 0)) + 1
            s["lamp_until"] = now + timedelta(hours=3)
            text = "💡\nТи поставив лампу.\nЯйце стало теплішим.\nЗдається, процес пішов швидше."
            # ТЗ: growth > stability * 1.5 → risk += 20 (при stability==0 вираз завжди true після лампи - не штрафуємо)
            stv = int(s["stability"])
            gr = int(s["growth"])
            if stv > 0 and gr > int(stv * 1.5):
                s["risk"] += 20
                text += "\n\n🔥\nЯйце занадто тепле.\nТи явно перестарався."
        elif action == "incubator":
            iu = _dt_naive_local(s.get("incubator_cooldown_until"))
            if iu and iu > now:
                cd_text = _fmt_remaining(s["incubator_cooldown_until"])
                await callback.answer(
                    f"⏱️ Інкубатор\nЩе залишилося {cd_text}.",
                    show_alert=True,
                )
                return
            if not deduct_balance(uid, INCUBATOR_COST):
                await callback.answer("Недостатньо 💵.", show_alert=True)
                return
            s["growth"] += 20
            s["stability"] += 15
            s["progress"] += random.randint(2, 4)
            s["incubator_uses"] = int(s.get("incubator_uses", 0)) + 1
            s["incubator_cooldown_until"] = now + timedelta(hours=5)
            text = "🧪\nТи підключив інкубатор.\nТепер усе під контролем… мабуть."
            if s["incubator_uses"] >= 3:
                s["risk"] += 15
                s["overcare_percent"] = int(s.get("overcare_percent", 0)) + 15
                text += "\n\n🌫\nТи занадто прискорюєш процес.\nЦе може погано закінчитись."
        elif action == "feed":
            fu = _dt_naive_local(s.get("feed_cooldown_until"))
            if fu and fu > now:
                cd_text = _fmt_remaining(s["feed_cooldown_until"])
                await callback.answer(
                    f"🍞 Корм\nЩе залишилося {cd_text}.",
                    show_alert=True,
                )
                return
            if not deduct_balance(uid, FEED_COST):
                await callback.answer("Недостатньо 💵.", show_alert=True)
                return
            s["quality"] += 25
            text = "🍞\nТи щось дав йому.\nВсередині стало тихіше.\nНаче воно… задоволене."
            s["feed_uses"] = int(s.get("feed_uses", 0)) + 1
            prev_feed_same_day = s.get("feed_date") == today
            s["feed_date"] = today
            s["feed_count"] = (int(s.get("feed_count", 0)) + 1) if prev_feed_same_day else 1
            s["feed_cooldown_until"] = now + FEED_COOLDOWN
            if s["feed_uses"] >= 5:
                s["overcare_percent"] = int(s.get("overcare_percent", 0)) + 4
            rem = _fmt_remaining(s["feed_cooldown_until"])
            cb_msg = f"🍞 Ще залишилося {rem}."
            cb_alert = True
        elif action == "clean":
            cu = _dt_naive_local(s.get("clean_cooldown_until"))
            if cu and cu > now:
                cd_text = _fmt_remaining(s["clean_cooldown_until"])
                await callback.answer(
                    f"🧼 Чистка\nЩе залишилося {cd_text}.",
                    show_alert=True,
                )
                return
            if not deduct_balance(uid, CLEAN_COST):
                await callback.answer("Недостатньо 💵.", show_alert=True)
                return
            s["stability"] += 20
            s["risk"] -= 10
            text = "🧼\nТи очистив шкаралупу.\nТріщини стали чіткішими."
            s["clean_uses"] = int(s.get("clean_uses", 0)) + 1
            prev_clean_same_day = s.get("clean_date") == today
            s["clean_date"] = today
            s["clean_count"] = (int(s.get("clean_count", 0)) + 1) if prev_clean_same_day else 1
            s["clean_cooldown_until"] = now + CLEAN_COOLDOWN
            if s["clean_uses"] >= 5:
                s["overcare_percent"] = int(s.get("overcare_percent", 0)) + 4
            rem = _fmt_remaining(s["clean_cooldown_until"])
            cb_msg = f"🧼 Ще залишилося {rem}."
            cb_alert = True
        else:
            await callback.answer()
            return

        s["progress"] = max(0, min(100, s["progress"]))
        s["growth"] = max(0, min(100, s["growth"]))
        s["stability"] = max(0, min(100, s["stability"]))
        s["quality"] = max(0, min(100, s["quality"]))
        s["risk"] = max(0, min(100, s["risk"]))
        s["overcare_percent"] = max(0, min(100, int(s.get("overcare_percent", 0))))
        old_stage = s["stage"]
        s["stage"] = _stage_from_progress(s["progress"])
        s["pending_hint"] = pending_override if pending_override is not None else _PENDING_AFTER_ACTION.get(action)
        _upsert_state(uid, s)

        if s["stage"] > old_stage:
            stage_msgs = {
                2: "🥚\nНа шкаралупі з'явились тріщини.\nТи точно нічого не зламав?",
                3: "🥚\nЯйце стало теплим.\nІноді здається, що воно реагує на тебе.",
                4: "🥚\nВсередині щось рухається.\nІ це вже не жарти.",
                5: "🥚\nШкаралупа ледве тримається.\nСкоро.",
            }
            text += f"\n\n{stage_msgs.get(s['stage'], '')}"

        try:
            raw_panel = _egg_panel_raw_html(uid, s, action_feedback=text, consume_pending=False)
            await _egg_try_edit(callback.message, raw_panel, _main_kb(), _main_kb_plain())
        except Exception:
            pass
        await callback.answer(cb_msg or "Готово.", show_alert=cb_alert)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            await callback.answer("Сталася помилка, спробуй ще раз.", show_alert=True)
        except Exception:
            pass


@router_egg.callback_query(F.data == "egg:lamp")
async def egg_lamp(callback: CallbackQuery):
    await _apply_action(callback, "lamp")


@router_egg.callback_query(F.data == "egg:incubator")
async def egg_incubator(callback: CallbackQuery):
    await _apply_action(callback, "incubator")


@router_egg.callback_query(F.data == "egg:feed")
async def egg_feed(callback: CallbackQuery):
    await _apply_action(callback, "feed")


@router_egg.callback_query(F.data == "egg:clean")
async def egg_clean(callback: CallbackQuery):
    await _apply_action(callback, "clean")


@router_egg.callback_query(F.data == "egg:open")
async def egg_open(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        return await callback.answer()
    uid = int(callback.from_user.id)
    s = _get_state(uid)
    if not s or not s["has_egg"]:
        await callback.answer("Спершу візьми яйце через /egg.", show_alert=True)
        return
    if s["opened"]:
        await callback.answer("Уже відкрите.", show_alert=True)
        return
    if not _can_open_today(uid):
        await callback.answer("Ще не час відкривати.", show_alert=True)
        return

    stb = int(s["stability"])
    q = int(s["quality"])
    r = int(s["risk"])
    if r >= 60:
        result = "fail"
    elif q >= 60 and stb >= 40:
        result = "perfect"
    elif stb >= 50:
        result = "safe"
    elif q >= 40:
        result = "good"
    else:
        result = "normal"

    payout = 0
    result_text = ""
    extra_lines = []
    if result == "perfect":
        payout = 1000
        rare_name = _grant_rare_buff(uid)
        result_text = "🐣\nВсе пройшло ідеально.\nТи зробив усе правильно."
        extra_lines = [f"💰 +{payout}", "🎁 Рідкісний баф", "🎟 Бонус"]
        if rare_name:
            extra_lines.append(f"📦 {rare_name}")
    elif result == "good":
        payout = 7000
        result_text = "🐣\nНепогано.\nТи явно старався."
        extra_lines = [f"💰 +{payout}", "📦 Кейс"]
    elif result == "normal":
        payout = 5000
        result_text = "🐣\nНу… хоча б не дарма."
        extra_lines = [f"💰 +{payout}"]
    elif result == "safe":
        payout = 2000
        result_text = "🐣\nБез сюрпризів.\nАле й без провалів."
        extra_lines = [f"💰 +{payout}"]
    else:
        payout = random.randint(0, 500)
        result_text = "🐣\nТріщина пішла не туди.\n💀\nТи щось зробив не так."
        extra_lines = [f"💰 +{payout}"]

    if payout > 0:
        add_balance_to_user(uid, payout)

    s["opened"] = True
    s["result_type"] = result
    _upsert_state(uid, s)
    _db_execute(
        "UPDATE egg_event_state SET opened_at = CURRENT_TIMESTAMP WHERE user_id = %s",
        (uid,),
    )
    conn.commit()

    intro = (
        "🐣\nШкаралупа тріснула.\nТи довго з ним возився.\nТепер подивимось, чи воно того варте."
    )
    try:
        await _egg_try_edit(callback.message, intro, None, None)
    except Exception:
        await _egg_answer_html(callback.message, intro)
    await callback.answer("Відкриваємо...")
    await asyncio.sleep(random.uniform(1.0, 2.0))
    await _egg_answer_html(callback.message, result_text + "\n\n" + "\n".join(extra_lines))
    await callback.message.answer(
        _egg_premium_html(
            "📊\n"
            f"Твоє яйце:\n"
            f"Ріст: {_progress_bar(s['growth'])}\n"
            f"Стабільність: {_progress_bar(s['stability'])}\n"
            f"Якість: {_progress_bar(s['quality'])}\n"
            f"Ризик: {_progress_bar(s['risk'])}"
        ),
        parse_mode="html",
    )


def _is_test_admin(user_id: int) -> bool:
    return int(user_id) == BOT_OWNER_ID


@router_egg.message(Command("egg_reset"))
async def egg_reset_cmd(message: Message):
    """Тест: повний скидання яйця для user_id (або себе)."""
    if message.chat.type != "private" or not message.from_user:
        return
    if not _is_test_admin(message.from_user.id):
        await message.answer(_egg_premium_html("❌ Тільки тест-адмін."), parse_mode="html")
        return
    parts = (message.text or "").strip().split()
    target_id = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else int(message.from_user.id)
    try:
        _db_execute("DELETE FROM egg_event_state WHERE user_id = %s", (target_id,))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await message.answer(_egg_premium_html("❌ Не вдалося скинути."), parse_mode="html")
        return
    await message.answer(
        _egg_premium_html(f"✅ /egg скинуто для <code>{target_id}</code>."),
        parse_mode="html",
    )


@router_egg.message(Command("egg_set"))
async def egg_set_cmd(message: Message):
    """
    Тест: швидко виставити стати.
    Формат:
    /egg_set <uid|me> <progress> <growth> <stability> <quality> <risk> [opened:0|1]
    """
    if message.chat.type != "private" or not message.from_user:
        return
    if not _is_test_admin(message.from_user.id):
        await message.answer(_egg_premium_html("❌ Тільки тест-адмін."), parse_mode="html")
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 7:
        await message.answer(
            _egg_premium_html(
                "Використання:\n"
                "<code>/egg_set &lt;uid|me&gt; &lt;progress&gt; &lt;growth&gt; &lt;stability&gt; &lt;quality&gt; &lt;risk&gt; [opened]</code>\n\n"
                "Приклад:\n"
                "<code>/egg_set me 85 70 55 80 20 0</code>"
            ),
            parse_mode="html",
        )
        return
    uid_raw = parts[1].lower()
    if uid_raw == "me":
        uid = int(message.from_user.id)
    elif uid_raw.lstrip("-").isdigit():
        uid = int(uid_raw)
    else:
        await message.answer(_egg_premium_html("❌ Невірний uid."), parse_mode="html")
        return
    try:
        progress = max(0, min(100, int(parts[2])))
        growth = max(0, min(100, int(parts[3])))
        stability = max(0, min(100, int(parts[4])))
        quality = max(0, min(100, int(parts[5])))
        risk = max(0, min(100, int(parts[6])))
        opened = bool(int(parts[7])) if len(parts) > 7 else False
    except Exception:
        await message.answer(_egg_premium_html("❌ Невірні числа."), parse_mode="html")
        return

    try:
        row = _db_fetchone("SELECT 1 FROM users WHERE id = %s", (uid,))
        if row is None:
            _db_execute("INSERT INTO users (id, tg_name, link) VALUES (%s, %s, %s)", (uid, None, None))
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    s = _get_state(uid) or {
        "has_egg": True, "stage": 1, "progress": 0, "growth": 0, "stability": 0, "quality": 0, "risk": 0,
        "lamp_until": None, "incubator_cooldown_until": None, "lamp_uses": 0, "incubator_uses": 0, "feed_uses": 0, "clean_uses": 0, "overcare_percent": 0, "feed_date": None, "feed_count": 0,
        "clean_date": None, "clean_count": 0, "opened": False, "result_type": None, "pending_hint": None,
        "feed_cooldown_until": None, "clean_cooldown_until": None,
    }
    s["has_egg"] = True
    s["progress"] = progress
    s["growth"] = growth
    s["stability"] = stability
    s["quality"] = quality
    s["risk"] = risk
    s["stage"] = _stage_from_progress(progress)
    s["opened"] = opened
    s["result_type"] = None
    s["lamp_until"] = None
    s["incubator_cooldown_until"] = None
    s["lamp_uses"] = 0
    s["incubator_uses"] = 0
    s["feed_uses"] = 0
    s["clean_uses"] = 0
    s["overcare_percent"] = 0
    s["feed_date"] = None
    s["feed_count"] = 0
    s["clean_date"] = None
    s["clean_count"] = 0
    s["pending_hint"] = None
    s["feed_cooldown_until"] = None
    s["clean_cooldown_until"] = None
    try:
        _upsert_state(uid, s)
        if opened:
            _db_execute(
                "UPDATE egg_event_state SET opened_at = CURRENT_TIMESTAMP WHERE user_id = %s",
                (uid,),
            )
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await message.answer(_egg_premium_html("❌ Не вдалося зберегти."), parse_mode="html")
        return

    await message.answer(
        _egg_premium_html(
            f"✅ Налаштовано для <code>{uid}</code>\n"
            f"stage={s['stage']} progress={progress} growth={growth} stability={stability} quality={quality} risk={risk} opened={int(opened)}"
        ),
        parse_mode="html",
    )


@router_egg.message(Command("egg_open_now"))
async def egg_open_now_cmd(message: Message):
    """Тест: миттєво дати кнопку відкриття (без чекання дати) для user_id або себе."""
    if message.chat.type != "private" or not message.from_user:
        return
    if not _is_test_admin(message.from_user.id):
        await message.answer(_egg_premium_html("❌ Тільки тест-адмін."), parse_mode="html")
        return
    parts = (message.text or "").strip().split()
    uid = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else int(message.from_user.id)
    s = _get_state(uid)
    if not s:
        s = {
            "has_egg": True, "stage": 1, "progress": 0, "growth": 0, "stability": 0, "quality": 0, "risk": 0,
            "lamp_until": None, "incubator_cooldown_until": None, "lamp_uses": 0, "incubator_uses": 0, "feed_uses": 0, "clean_uses": 0, "overcare_percent": 0, "feed_date": None, "feed_count": 0,
            "clean_date": None, "clean_count": 0, "opened": False, "result_type": None, "pending_hint": None,
            "feed_cooldown_until": None, "clean_cooldown_until": None,
        }
    s["has_egg"] = True
    s["opened"] = False
    _upsert_state(uid, s)
    if uid == int(message.from_user.id):
        await _egg_try_answer(
            message,
            "🐣\nСьогодні.\nБільше нічого змінити не можна.",
            _open_kb(),
            _open_kb_plain(),
        )
    else:
        await message.answer(
            _egg_premium_html(
                f"✅ Для <code>{uid}</code> підготовлено стан для відкриття.\n"
                "Нехай виконає /egg у ЛС."
            ),
            parse_mode="html",
        )
