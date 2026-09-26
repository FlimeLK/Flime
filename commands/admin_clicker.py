"""
Адміністраторський клікер (noir-стиль «Sicilian Mafia»).

Команди в групах:
  /on   — відкрити зміну (лічильник активності) + анімація роботи   [для ВСІХ у чаті]
  /off  — закрити зміну, показати фактичний час                      [для ВСІХ у чаті]

  /clickermode      — режим тиші (бот реагує лише на клікер)          [лише власники бота]
  /clicker_setwork  — (reply на GIF/відео) анімація «роботи»          [лише власники бота]
  /clicker_setclap  — (reply на GIF) анімація оплесків                [лише власники бота]
  /clicker          — довідка/статус                                  [лише власники бота]

Механіка:
  * Лічильник рахує секунди активності.
  * Кожна повна година: тег учасників + GIF оплесків + 1 золото адміну.
  * Після години бот тегає адміна з кнопкою «Продовжити». Якщо за 10 хв не
    підтвердив — зміна автоматично знімається.
  * Усе зберігається в БД і переживає рестарт. Завершені зміни логуються для
    статистики (день/тиждень) в адмін-панелі /capone_admin.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from aiogram import Bot, Router, F
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database.database import (
    conn,
    cursor,
    run_db_call_async,
    add_gold_to_user_async,
    ping_members_add_async,
    ping_members_get_recent_async,
    ping_opt_out_ids_for_chat,
)
from premium_emoji import emoji_to_premium
from commands import vip as vip_mod

router_clicker = Router()

SHIFT_HOUR_SECONDS = 3600          # 1 година
CONTINUE_WINDOW_SECONDS = 600      # 10 хв на підтвердження
REWARD_GOLD = 1
CAPTION_UPDATE_INTERVAL = 60
TAG_CHUNK_SIZE = 6
TAG_MAX_USERS = 50
TAG_EMOJIS = ("🎩", "🥂", "🍾", "🔥", "✨", "👏")

_ALLOWED_LOCKDOWN_CMDS = (
    "on", "off", "clickermode", "clicker",
    "clicker_setwork", "clicker_setclap",
)

_clicker_only_chats: set[int] = set()
_shift_tasks: dict[tuple[int, int], list[asyncio.Task]] = {}


# ───────────────────────── DB ─────────────────────────
def _ensure_tables() -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clicker_only_chats (
            chat_id BIGINT PRIMARY KEY,
            enabled_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clicker_shifts (
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            cycle_started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            anim_msg_id BIGINT,
            is_anim BOOLEAN NOT NULL DEFAULT FALSE,
            hours_completed INTEGER NOT NULL DEFAULT 0,
            continue_deadline TIMESTAMP,
            PRIMARY KEY (chat_id, user_id)
        )""")
    # Міграція старої схеми (якщо таблиця вже існувала без нових колонок).
    for col, ddl in (
        ("cycle_started_at", "ALTER TABLE clicker_shifts ADD COLUMN IF NOT EXISTS cycle_started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("hours_completed", "ALTER TABLE clicker_shifts ADD COLUMN IF NOT EXISTS hours_completed INTEGER NOT NULL DEFAULT 0"),
        ("continue_deadline", "ALTER TABLE clicker_shifts ADD COLUMN IF NOT EXISTS continue_deadline TIMESTAMP"),
    ):
        try:
            cursor.execute(ddl)
        except Exception:
            pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clicker_media (
            name TEXT PRIMARY KEY,
            file_id TEXT NOT NULL
        )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clicker_shift_log (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            started_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            hours_completed INTEGER NOT NULL DEFAULT 0,
            end_reason TEXT NOT NULL DEFAULT 'off'
        )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_clicker_log_ended ON clicker_shift_log(ended_at)")
    conn.commit()


def _db_load_only_chats() -> set[int]:
    cursor.execute("SELECT chat_id FROM clicker_only_chats")
    return {int(r[0]) for r in (cursor.fetchall() or [])}


def _db_set_only(chat_id: int, on: bool) -> None:
    if on:
        cursor.execute("INSERT INTO clicker_only_chats (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (int(chat_id),))
    else:
        cursor.execute("DELETE FROM clicker_only_chats WHERE chat_id = %s", (int(chat_id),))
    conn.commit()


def _db_shift_start(chat_id: int, user_id: int, anim_msg_id, is_anim: bool) -> None:
    cursor.execute("""
        INSERT INTO clicker_shifts (chat_id, user_id, started_at, cycle_started_at, anim_msg_id, is_anim, hours_completed, continue_deadline)
        VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s, 0, NULL)
        ON CONFLICT (chat_id, user_id) DO UPDATE
        SET started_at=CURRENT_TIMESTAMP, cycle_started_at=CURRENT_TIMESTAMP,
            anim_msg_id=EXCLUDED.anim_msg_id, is_anim=EXCLUDED.is_anim,
            hours_completed=0, continue_deadline=NULL
    """, (int(chat_id), int(user_id), anim_msg_id, bool(is_anim)))
    conn.commit()


def _db_shift_get(chat_id: int, user_id: int):
    cursor.execute("""
        SELECT started_at, cycle_started_at, anim_msg_id, is_anim, hours_completed, continue_deadline
        FROM clicker_shifts WHERE chat_id=%s AND user_id=%s
    """, (int(chat_id), int(user_id)))
    return cursor.fetchone()


def _db_shift_new_cycle(chat_id: int, user_id: int) -> None:
    cursor.execute("UPDATE clicker_shifts SET cycle_started_at=CURRENT_TIMESTAMP, continue_deadline=NULL WHERE chat_id=%s AND user_id=%s", (int(chat_id), int(user_id)))
    conn.commit()


def _db_shift_set_deadline(chat_id: int, user_id: int, deadline_epoch: float) -> None:
    cursor.execute("UPDATE clicker_shifts SET continue_deadline=to_timestamp(%s), hours_completed=hours_completed+1 WHERE chat_id=%s AND user_id=%s", (deadline_epoch, int(chat_id), int(user_id)))
    conn.commit()


def _db_shift_end(chat_id: int, user_id: int) -> None:
    cursor.execute("DELETE FROM clicker_shifts WHERE chat_id=%s AND user_id=%s", (int(chat_id), int(user_id)))
    conn.commit()


def _db_load_active_shifts():
    cursor.execute("SELECT chat_id, user_id, started_at, cycle_started_at, anim_msg_id, is_anim, hours_completed, continue_deadline FROM clicker_shifts")
    return cursor.fetchall() or []


def _db_log_shift(chat_id, user_id, started_at, duration, hours, reason) -> None:
    cursor.execute("""
        INSERT INTO clicker_shift_log (chat_id, user_id, started_at, duration_seconds, hours_completed, end_reason)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (int(chat_id), int(user_id), started_at, int(duration), int(hours), reason))
    conn.commit()


def _db_set_media(name: str, file_id: str) -> None:
    cursor.execute("INSERT INTO clicker_media (name, file_id) VALUES (%s, %s) ON CONFLICT (name) DO UPDATE SET file_id=EXCLUDED.file_id", (name, file_id))
    conn.commit()


def _db_get_media(name: str):
    cursor.execute("SELECT file_id FROM clicker_media WHERE name=%s", (name,))
    r = cursor.fetchone()
    return r[0] if r else None


def _db_ensure_user(user_id: int) -> None:
    cursor.execute("INSERT INTO users (id, balance) VALUES (%s, 0) ON CONFLICT (id) DO NOTHING", (int(user_id),))
    conn.commit()


def _db_names_for(ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    cursor.execute("SELECT id, tg_name FROM users WHERE id = ANY(%s)", (list(ids),))
    return {int(r[0]): (r[1] or "Гравець") for r in (cursor.fetchall() or [])}


def _db_stats(chat_id=None):
    """Статистика за сьогодні та за 7 днів. Якщо chat_id заданий — лише цей чат."""
    out = {}
    chat_clause = " AND chat_id = %s" if chat_id is not None else ""
    extra = (int(chat_id),) if chat_id is not None else ()
    for key, where in (("day", "ended_at::date = CURRENT_DATE"), ("week", "ended_at >= NOW() - INTERVAL '7 days'")):
        cursor.execute(
            f"SELECT COUNT(*), COALESCE(SUM(duration_seconds),0), COALESCE(SUM(hours_completed),0), COUNT(DISTINCT user_id) "
            f"FROM clicker_shift_log WHERE {where}{chat_clause}",
            extra,
        )
        row = cursor.fetchone() or (0, 0, 0, 0)
        cursor.execute(
            f"SELECT l.user_id, COALESCE(u.tg_name,'Адмін') AS name, SUM(l.duration_seconds) AS d, SUM(l.hours_completed) AS h "
            f"FROM clicker_shift_log l LEFT JOIN users u ON u.id = l.user_id "
            f"WHERE {where}{chat_clause} GROUP BY l.user_id, u.tg_name ORDER BY d DESC LIMIT 5",
            extra,
        )
        top = cursor.fetchall() or []
        out[key] = {
            "shifts": int(row[0]), "duration": int(row[1]),
            "hours": int(row[2]), "admins": int(row[3]),
            "top": [(int(t[0]), t[1], int(t[2]), int(t[3])) for t in top],
        }
    return out


# ───────────────────────── helpers ─────────────────────────
def _fmt_dur(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _fmt_human(seconds: float) -> str:
    s = max(0, int(seconds)); h = s // 3600; m = (s % 3600) // 60
    if h and m:
        return f"{h} год {m} хв"
    if h:
        return f"{h} год"
    return f"{m} хв"


def _epoch(ts) -> float:
    if isinstance(ts, datetime):
        return ts.timestamp()
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except Exception:
        return time.time()


def _is_owner(user_id: int) -> bool:
    try:
        return vip_mod.is_bot_founder(int(user_id))
    except Exception:
        return False


def _is_group(message: Message) -> bool:
    return bool(message.chat) and message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def _off_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Закрити зміну", callback_data=f"clk:off:{user_id}")]])


def _continue_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Лишаюсь на зміні", callback_data=f"clk:cont:{user_id}"),
        InlineKeyboardButton(text="⏹ Закрити", callback_data=f"clk:off:{user_id}"),
    ]])


def _cancel_shift_tasks(chat_id: int, user_id: int) -> None:
    for t in _shift_tasks.pop((int(chat_id), int(user_id)), []) or []:
        if t and not t.done():
            try:
                t.cancel()
            except Exception:
                pass


# ───────────────────────── фонові задачі ─────────────────────────
async def _caption_updater(bot: Bot, chat_id: int, user_id: int, total_epoch: float, anim_msg_id: int, is_anim: bool):
    while True:
        await asyncio.sleep(CAPTION_UPDATE_INTERVAL)
        row = await run_db_call_async(_db_shift_get, chat_id, user_id)
        if not row:
            return
        elapsed = time.time() - total_epoch
        text = emoji_to_premium(
            "🗂 <b>МАФІЯ · КАБІНЕТ АДМІНІСТРАТОРА</b>\n"
            "<pre>Зміна триває. Район під наглядом.\n\n"
            f"Хронометр . . . {_fmt_dur(elapsed)}\n"
            "Статус . . . . . на зміні</pre>"
        )
        try:
            if is_anim:
                await bot.edit_message_caption(chat_id=chat_id, message_id=anim_msg_id, caption=text, parse_mode="html", reply_markup=_off_keyboard(user_id))
            else:
                await bot.edit_message_text(chat_id=chat_id, message_id=anim_msg_id, text=text, parse_mode="html", reply_markup=_off_keyboard(user_id))
        except Exception:
            pass


async def _hour_trigger(bot: Bot, chat_id: int, user_id: int, cycle_epoch: float):
    delay = SHIFT_HOUR_SECONDS - (time.time() - cycle_epoch)
    if delay > 0:
        await asyncio.sleep(delay)
    row = await run_db_call_async(_db_shift_get, chat_id, user_id)
    if not row:
        return
    # Якщо цикл уже інший (продовжили вручну) — ця задача застаріла.
    if abs(_epoch(row[1]) - cycle_epoch) > 2:
        return
    # +1 година, дедлайн на продовження, винагорода
    deadline = time.time() + CONTINUE_WINDOW_SECONDS
    await run_db_call_async(_db_shift_set_deadline, chat_id, user_id, deadline)
    try:
        await run_db_call_async(_db_ensure_user, user_id)
        await add_gold_to_user_async(user_id, REWARD_GOLD)
    except Exception:
        pass
    admin_name = await _name_of(bot, chat_id, user_id)
    await _applause_and_tags(bot, chat_id, admin_name)
    # Тег адміна + кнопка продовження
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=emoji_to_premium(
                f"⏳ <a href='tg://user?id={user_id}'>{admin_name}</a>, зміну зафіксовано — рівно 60 хвилин.\n"
                "Лишаєшся в кабінеті? Маєш <b>10 хвилин</b> на відповідь —\n"
                "інакше справу закриють автоматично."
            ),
            parse_mode="html",
            reply_markup=_continue_keyboard(user_id),
        )
    except Exception:
        pass
    # Таймер автозняття
    _shift_tasks.setdefault((int(chat_id), int(user_id)), []).append(
        asyncio.create_task(_auto_remove(bot, chat_id, user_id, deadline))
    )


async def _auto_remove(bot: Bot, chat_id: int, user_id: int, deadline_epoch: float):
    wait = deadline_epoch - time.time()
    if wait > 0:
        await asyncio.sleep(wait)
    row = await run_db_call_async(_db_shift_get, chat_id, user_id)
    if not row:
        return
    # continue_deadline очищується при продовженні → якщо None, людина продовжила.
    if row[5] is None:
        return
    if _epoch(row[5]) - time.time() > 2:
        return  # дедлайн перенесли (нова година) — не чіпаємо
    await _end_and_log(bot, chat_id, user_id, reason="auto", edit_msg_id=None)


async def _name_of(bot: Bot, chat_id: int, user_id: int) -> str:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        if m and getattr(m, "user", None):
            return m.user.full_name or m.user.first_name or "Адмін"
    except Exception:
        pass
    return "Адмін"


async def _applause_and_tags(bot: Bot, chat_id: int, admin_name: str):
    # Внутрішній «звіт Мафії» + GIF оплесків.
    report = emoji_to_premium(
        "📜 <b>ВНУТРІШНІЙ ЗВІТ «МАФІЇ»</b>\n"
        "<i>—————————————</i>\n"
        f"Адміністратор <b>{admin_name}</b> відпрацював повну зміну.\n\n"
        "Ваша старанність оцінена.\n"
        f"🪙 <b>+{REWARD_GOLD} золото</b> зараховано на баланс Мафії."
    )
    clap = await run_db_call_async(_db_get_media, "applause")
    ok = False
    if clap:
        try:
            await bot.send_animation(chat_id=chat_id, animation=clap, caption=report, parse_mode="html")
            ok = True
        except Exception:
            ok = False
    if not ok:
        try:
            await bot.send_message(chat_id=chat_id, text=report, parse_mode="html")
        except Exception:
            pass
    # Іменні теги «кращих серед нас».
    try:
        ids = set(await ping_members_get_recent_async(chat_id, limit=200))
    except Exception:
        ids = set()
    try:
        opt = set(await run_db_call_async(ping_opt_out_ids_for_chat, chat_id) or [])
    except Exception:
        opt = set()
    try:
        bot_id = (await bot.me()).id
    except Exception:
        bot_id = 0
    tag_ids = sorted(u for u in ids if u not in opt and u != bot_id)[:TAG_MAX_USERS]
    if not tag_ids:
        return
    names = await run_db_call_async(_db_names_for, tag_ids)
    mentions = [f"<a href='tg://user?id={u}'>{(names.get(u) or 'Гравець')}</a>" for u in tag_ids]
    for i in range(0, len(mentions), 15):
        chunk = mentions[i:i + 15]
        prefix = "🥂 <b>Вітаємо кращих серед нас:</b>\n" if i == 0 else ""
        try:
            await bot.send_message(chat_id=chat_id, text=emoji_to_premium(prefix + ", ".join(chunk)), parse_mode="html")
        except Exception:
            pass
        await asyncio.sleep(0.4)


def _start_shift_tasks(bot: Bot, chat_id: int, user_id: int, total_epoch: float, cycle_epoch: float, anim_msg_id: int, is_anim: bool):
    _cancel_shift_tasks(chat_id, user_id)
    _shift_tasks[(int(chat_id), int(user_id))] = [
        asyncio.create_task(_caption_updater(bot, chat_id, user_id, total_epoch, anim_msg_id, is_anim)),
        asyncio.create_task(_hour_trigger(bot, chat_id, user_id, cycle_epoch)),
    ]


async def _end_and_log(bot: Bot, chat_id: int, user_id: int, reason: str, edit_msg_id, is_anim: bool = False):
    row = await run_db_call_async(_db_shift_get, chat_id, user_id)
    if not row:
        return None
    total_epoch = _epoch(row[0])
    anim_msg_id = row[2]
    is_anim_db = bool(row[3])
    hours = int(row[4] or 0)
    elapsed = time.time() - total_epoch
    _cancel_shift_tasks(chat_id, user_id)
    await run_db_call_async(_db_shift_end, chat_id, user_id)
    try:
        await run_db_call_async(_db_log_shift, chat_id, user_id, row[0], elapsed, hours, reason)
    except Exception:
        pass

    if reason == "auto":
        gold_line = (f"\nПовних годин: {hours}" if hours else "")
        text = emoji_to_premium(
            "🗂 <b>СПРАВУ ЗАКРИТО</b>\n"
            "<pre>Підтвердження не надійшло за 10 хв.\n\n"
            f"Відпрацьовано: {_fmt_dur(elapsed)}{gold_line}</pre>"
        )
    else:
        gold_line = (f"\nПовних годин: {hours}  (+{hours} золота)" if hours else "")
        text = emoji_to_premium(
            "🗂 <b>КАБІНЕТ ЗАЧИНЕНО</b>\n"
            "<pre>Зміну завершено.\n\n"
            f"Відпрацьовано: {_fmt_dur(elapsed)}{gold_line}</pre>"
        )
    mid = edit_msg_id if edit_msg_id is not None else anim_msg_id
    use_anim = is_anim if edit_msg_id is not None else is_anim_db
    edited = False
    if mid:
        try:
            if use_anim:
                await bot.edit_message_caption(chat_id=chat_id, message_id=mid, caption=text, parse_mode="html", reply_markup=None)
            else:
                await bot.edit_message_text(chat_id=chat_id, message_id=mid, text=text, parse_mode="html", reply_markup=None)
            edited = True
        except Exception:
            edited = False
    if not edited:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
    return elapsed


# ───────────────────────── команди ─────────────────────────
@router_clicker.message(Command("on"))
async def cmd_on(message: Message, bot: Bot):
    if not _is_group(message) or not message.from_user:
        return
    chat_id, user_id = int(message.chat.id), int(message.from_user.id)
    existing = await run_db_call_async(_db_shift_get, chat_id, user_id)
    if existing:
        elapsed = time.time() - _epoch(existing[0])
        await message.reply(emoji_to_premium(f"🗂 Кабінет уже відкрито: <b>{_fmt_dur(elapsed)}</b>.\nЗакрити зміну — /off."), parse_mode="html")
        return
    caption = emoji_to_premium(
        "🗂 <b>МАФІЯ · КАБІНЕТ АДМІНІСТРАТОРА</b>\n"
        "<pre>Кабінет адміністратора відкритий.\n"
        "Час пішов, Бос.\n\n"
        "Хронометр . . . 00:00:00\n"
        "Статус . . . . . на зміні</pre>"
    )
    work = await run_db_call_async(_db_get_media, "work")
    anim_msg_id, is_anim = None, False
    if work:
        try:
            sent = await bot.send_animation(chat_id=chat_id, animation=work, caption=caption, parse_mode="html", reply_markup=_off_keyboard(user_id))
            anim_msg_id, is_anim = sent.message_id, True
        except Exception:
            anim_msg_id = None
    if anim_msg_id is None:
        sent = await message.answer(caption, parse_mode="html", reply_markup=_off_keyboard(user_id))
        anim_msg_id, is_anim = sent.message_id, False
    await run_db_call_async(_db_shift_start, chat_id, user_id, anim_msg_id, is_anim)
    now = time.time()
    _start_shift_tasks(bot, chat_id, user_id, now, now, anim_msg_id, is_anim)


@router_clicker.message(Command("off"))
async def cmd_off(message: Message, bot: Bot):
    if not _is_group(message) or not message.from_user:
        return
    chat_id, user_id = int(message.chat.id), int(message.from_user.id)
    row = await run_db_call_async(_db_shift_get, chat_id, user_id)
    if not row:
        await message.reply("🗂 Кабінет зачинено. Відкрий зміну через /on.")
        return
    await _end_and_log(bot, chat_id, user_id, reason="off", edit_msg_id=None)


@router_clicker.callback_query(F.data.startswith("clk:off:"))
async def cb_off(callback: CallbackQuery, bot: Bot):
    if not callback.from_user or not callback.message:
        return
    try:
        owner_id = int((callback.data or "").split(":")[2])
    except Exception:
        await callback.answer(); return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя зміна.", show_alert=True); return
    await callback.answer()
    await _end_and_log(bot, int(callback.message.chat.id), owner_id, reason="off", edit_msg_id=callback.message.message_id, is_anim=bool(callback.message.animation))


@router_clicker.callback_query(F.data.startswith("clk:cont:"))
async def cb_continue(callback: CallbackQuery, bot: Bot):
    if not callback.from_user or not callback.message:
        return
    try:
        owner_id = int((callback.data or "").split(":")[2])
    except Exception:
        await callback.answer(); return
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя зміна.", show_alert=True); return
    chat_id = int(callback.message.chat.id)
    row = await run_db_call_async(_db_shift_get, chat_id, owner_id)
    if not row:
        await callback.answer("Зміну вже закрито.", show_alert=True); return
    await callback.answer("Зміну продовжено 🤝")
    await run_db_call_async(_db_shift_new_cycle, chat_id, owner_id)
    # Перезапуск циклу
    total_epoch = _epoch(row[0])
    now = time.time()
    _start_shift_tasks(bot, chat_id, owner_id, total_epoch, now, int(row[2] or 0), bool(row[3]))
    try:
        await callback.message.edit_text(emoji_to_premium("🤝 <b>Справу продовжено.</b>\n<i>Ще одна година під твоїм наглядом, Бос.</i>"), parse_mode="html")
    except Exception:
        pass


# ── Команди лише для власників бота ──
@router_clicker.message(Command("clickermode"))
async def cmd_clickermode(message: Message, bot: Bot):
    if not _is_group(message) or not message.from_user:
        return
    if not _is_owner(message.from_user.id):
        await message.reply("⛔️ Лише власники бота керують режимом.")
        return
    chat_id = int(message.chat.id)
    now_on = chat_id not in _clicker_only_chats
    await run_db_call_async(_db_set_only, chat_id, now_on)
    if now_on:
        _clicker_only_chats.add(chat_id)
        await message.reply(emoji_to_premium(
            "🔒 <b>Режим тиші — увімкнено.</b>\n\n"
            "У цьому чаті бот тримає язик за зубами: реагує лише на <code>/on</code> та <code>/off</code> "
            "(і службові команди власників). Решта — повз вуха, щоб без хаосу.\n\n"
            "Вимкнути — знову <code>/clickermode</code>."
        ), parse_mode="html")
    else:
        _clicker_only_chats.discard(chat_id)
        await message.reply(emoji_to_premium("🔓 <b>Режим тиші — вимкнено.</b>\nБот знову чує всі команди."), parse_mode="html")


async def _set_media_cmd(message: Message, bot: Bot, name: str, label: str):
    if not _is_group(message) or not message.from_user:
        return
    if not _is_owner(message.from_user.id):
        await message.reply("⛔️ Лише власники бота.")
        return
    reply = message.reply_to_message
    file_id = None
    if reply:
        if reply.animation:
            file_id = reply.animation.file_id
        elif reply.video:
            file_id = reply.video.file_id
        elif reply.document:
            file_id = reply.document.file_id
    if not file_id:
        await message.reply(f"↩️ Зроби reply на GIF/відео й напиши команду, щоб задати анімацію «{label}».")
        return
    await run_db_call_async(_db_set_media, name, file_id)
    await message.reply(emoji_to_premium(f"✅ Анімацію «{label}» збережено."), parse_mode="html")


@router_clicker.message(Command("clicker_setwork"))
async def cmd_setwork(message: Message, bot: Bot):
    await _set_media_cmd(message, bot, "work", "робота")


@router_clicker.message(Command("clicker_setclap"))
async def cmd_setclap(message: Message, bot: Bot):
    await _set_media_cmd(message, bot, "applause", "оплески")


@router_clicker.message(Command("clicker"))
async def cmd_clicker(message: Message, bot: Bot):
    if not _is_group(message) or not message.from_user:
        return
    if not _is_owner(message.from_user.id):
        return  # тихо ігноруємо не-власників
    locked = int(message.chat.id) in _clicker_only_chats
    await message.reply(emoji_to_premium(
        "🕹 <b>Адмін-клікер</b> <i>(noir)</i>\n"
        "━━━━━━━━━━━━━━━\n"
        "🟢 <code>/on</code> — відкрити зміну <i>(будь-хто)</i>\n"
        "🔴 <code>/off</code> — закрити зміну <i>(будь-хто)</i>\n\n"
        "<b>Лише власники:</b>\n"
        "🔒 <code>/clickermode</code> — режим тиші " + ("🔒 увімкнено" if locked else "🔓 вимкнено") + "\n"
        "🛠 <code>/clicker_setwork</code> — (reply GIF) анімація роботи\n"
        "👏 <code>/clicker_setclap</code> — (reply GIF) анімація оплесків\n\n"
        "<i>За кожну повну годину — теги команди, оплески й 1 золото. "
        "Після години є 10 хв, щоб лишитись на зміні.</i>"
    ), parse_mode="html")


# ───────────────────────── «Стата» в робочому чаті (для всіх) ─────────────────────────
def _is_stata_trigger(message: Message) -> bool:
    t = (message.text or "").strip().lower()
    return t in ("стата", "стату", "статистика")


def _stats_kb(active: str) -> InlineKeyboardMarkup:
    d = ("✅ " if active == "day" else "") + "📅 Сьогодні"
    w = ("✅ " if active == "week" else "") + "📆 Тиждень"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=d, callback_data="clk:stats:day"),
            InlineKeyboardButton(text=w, callback_data="clk:stats:week"),
        ],
        [InlineKeyboardButton(text="✖ Закрити", callback_data="clk:stats:close")],
    ])


@router_clicker.message(F.text, F.func(_is_stata_trigger))
async def cmd_stata(message: Message, bot: Bot):
    if not _is_group(message):
        return
    text = await render_clicker_stats(chat_id=int(message.chat.id), period="day")
    await message.answer(text, parse_mode="html", reply_markup=_stats_kb("day"))


@router_clicker.callback_query(F.data.startswith("clk:stats:"))
async def cb_stats(callback: CallbackQuery, bot: Bot):
    if not callback.message:
        return
    parts = (callback.data or "").split(":")
    action = parts[2] if len(parts) > 2 else "day"
    if action == "close":
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    period = action if action in ("day", "week") else "day"
    text = await render_clicker_stats(chat_id=int(callback.message.chat.id), period=period)
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="html", reply_markup=_stats_kb(period))
    except Exception:
        pass


# ───────────────────────── рендер статистики ─────────────────────────
async def render_clicker_stats(chat_id=None, period=None) -> str:
    try:
        data = await run_db_call_async(_db_stats, chat_id)
    except Exception as e:
        return emoji_to_premium(f"🕹 <b>Клікер — статистика</b>\n\n⚠️ Помилка: {e}")

    def _block(title: str, d: dict) -> str:
        lines = [
            f"<b>{title}</b>",
            f"• Змін: <b>{d['shifts']}</b>",
            f"• Відстояно: <b>{_fmt_human(d['duration'])}</b>",
            f"• Повних годин (золото): <b>{d['hours']}</b>",
            f"• Працівників: <b>{d['admins']}</b>",
        ]
        if d["top"]:
            lines.append("• Топ:")
            for uid, name, dur, hrs in d["top"]:
                nm = (name or "Адмін")[:22]
                lines.append(f"   ▫️ {nm} — {_fmt_human(dur)} ({hrs} год)")
        return "\n".join(lines)

    head = ""
    if period == "day":
        return emoji_to_premium(head + "📅 " + _block("Сьогодні", data["day"]))
    if period == "week":
        return emoji_to_premium(head + "📆 " + _block("За тиждень", data["week"]))
    return emoji_to_premium(head + "📅 " + _block("Сьогодні", data["day"]) + "\n\n📆 " + _block("За тиждень", data["week"]))


# ───────────────────────── режим тиші (middleware) ─────────────────────────
def _extract_cmd(text):
    if not text:
        return None
    t = text.strip()
    if not t.startswith("/"):
        return None
    word = t[1:].split()[0] if len(t) > 1 else ""
    return (word.split("@", 1)[0].lower()) or None


def _is_allowed_in_lockdown(event) -> bool:
    if isinstance(event, CallbackQuery):
        return bool(event.data and event.data.startswith("clk:"))
    if isinstance(event, Message):
        if _extract_cmd(event.text or event.caption) in _ALLOWED_LOCKDOWN_CMDS:
            return True
        return _is_stata_trigger(event)  # «Стата» доступна всім навіть у режимі тиші
    return True


class ClickerOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat_id = from_user = None
        if isinstance(event, Message):
            chat_id = event.chat.id if event.chat else None
            from_user = event.from_user
        elif isinstance(event, CallbackQuery):
            msg = event.message
            chat_id = msg.chat.id if msg and msg.chat else None
            from_user = event.from_user
        if chat_id is not None and int(chat_id) in _clicker_only_chats:
            if isinstance(event, Message) and from_user and not from_user.is_bot:
                try:
                    asyncio.create_task(ping_members_add_async(int(chat_id), int(from_user.id)))
                except Exception:
                    pass
            if not _is_allowed_in_lockdown(event):
                return
        return await handler(event, data)


# ───────────────────────── старт ─────────────────────────
async def clicker_init(bot: Bot) -> None:
    global _clicker_only_chats
    try:
        await run_db_call_async(_ensure_tables)
    except Exception as e:
        print(f"[clicker] ensure_tables error: {e}")
        return
    try:
        _clicker_only_chats = await run_db_call_async(_db_load_only_chats)
    except Exception:
        _clicker_only_chats = set()
    try:
        shifts = await run_db_call_async(_db_load_active_shifts)
    except Exception:
        shifts = []
    now = time.time()
    for row in shifts:
        try:
            chat_id, user_id, started_at, cycle_started_at, anim_msg_id, is_anim, hours, continue_deadline = row
            total_epoch = _epoch(started_at)
            if continue_deadline is not None:
                # Були у вікні продовження — відновлюємо таймер автозняття.
                dl = _epoch(continue_deadline)
                _cancel_shift_tasks(int(chat_id), int(user_id))
                _shift_tasks[(int(chat_id), int(user_id))] = [
                    asyncio.create_task(_caption_updater(bot, int(chat_id), int(user_id), total_epoch, int(anim_msg_id or 0), bool(is_anim))),
                    asyncio.create_task(_auto_remove(bot, int(chat_id), int(user_id), dl if dl > now else now + 1)),
                ]
            else:
                _start_shift_tasks(bot, int(chat_id), int(user_id), total_epoch, _epoch(cycle_started_at), int(anim_msg_id or 0), bool(is_anim))
        except Exception:
            continue
