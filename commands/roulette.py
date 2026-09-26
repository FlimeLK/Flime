from __future__ import annotations

import asyncio
import json
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.database import (
    conn,
    cursor,
    add_balance_to_user_async,
    deduct_balance_async,
    get_balance_async,
    roulette_get_profile_async,
    roulette_update_profile_async,
    run_db_call_async,
)
from premium_emoji import emoji_to_premium, custom_emoji_id_for_symbol

from commands import vip as vip_mod

router_roulette = Router()

# КД на повторний виклик меню рулетки (/roulette або текст «рулетка»/«рулетки»).
MENU_OPEN_COOLDOWN_SECONDS = 10
_menu_open_monotonic: dict[int, float] = {}

BET_MIN = 10
BET_MAX = 1_000_000_000_000
SPIN_TIMEOUT_SECONDS = 20
# Повільніша анімація = менше edit_message запитів.
SPIN_STREAM_FRAME_DELAY = 0.55
# ── Шанси рулетки залежно від гравця і розміру ставки ──
# 2 власники бота: фіксований шанс 55% на всі ставки (без анти-аб'юзу).
ROULETTE_OWNER_IDS = {1859870653}
ROULETTE_OWNER_WIN_CHANCE = 0.55
# Поріг «звичайної» ставки для НЕ-власників.
ROULETTE_NORMAL_BET_MAX = 1_000
# «Нормальні» (старі) шанси — для ставок ≤ порогу.
NORMAL_RED_WIN_CHANCE = 0.25
NORMAL_BLACK_WIN_CHANCE = 0.30
NORMAL_ALLIN_WIN_CHANCE = 0.08
# Урізані (поточні) шанси — для ставок > порогу.
NERF_RED_WIN_CHANCE = 0.01
NERF_BLACK_WIN_CHANCE = 0.02
NERF_ALLIN_WIN_CHANCE = 0.01

# Сумісність: старі імена → урізані значення (поведінка за замовчуванням для великих ставок).
BASE_RED_WIN_CHANCE = NERF_RED_WIN_CHANCE
BASE_BLACK_WIN_CHANCE = NERF_BLACK_WIN_CHANCE


def _is_roulette_owner(user_id: int) -> bool:
    try:
        return int(user_id) in ROULETTE_OWNER_IDS
    except Exception:
        return False


def _color_base_chance(user_id: int, bet: int, bet_type: str) -> float:
    """Базовий шанс для червоного/чорного з урахуванням власника і розміру ставки."""
    if _is_roulette_owner(user_id):
        return ROULETTE_OWNER_WIN_CHANCE
    if int(bet) <= ROULETTE_NORMAL_BET_MAX:
        return NORMAL_RED_WIN_CHANCE if bet_type == "red" else NORMAL_BLACK_WIN_CHANCE
    return NERF_RED_WIN_CHANCE if bet_type == "red" else NERF_BLACK_WIN_CHANCE


def _allin_base_chance(user_id: int, bet: int) -> float:
    """Базовий шанс для «Все або нічого» (x5)."""
    if _is_roulette_owner(user_id):
        return ROULETTE_OWNER_WIN_CHANCE
    if int(bet) <= ROULETTE_NORMAL_BET_MAX:
        return NORMAL_ALLIN_WIN_CHANCE
    return NERF_ALLIN_WIN_CHANCE


def _random_profit_allowed(user_id: int, bet: int) -> bool:
    """Чи дозволено прибуток на ставці «Рандом»: власникам — так; іншим — лише до порогу."""
    if _is_roulette_owner(user_id):
        return True
    return int(bet) <= ROULETTE_NORMAL_BET_MAX


def _db_fetchone_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_execute_sync(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0


def _db_commit_sync() -> None:
    conn.commit()


def _vip_display_emoji(tier: str | None) -> str:
    """Рядки про тариф: базовий VIP - ⚒️, VIP+ - ⛏️; без підписки - як базовий (апсел)."""
    symbol = "⛏️" if tier == "vip_plus" else "⚒️"
    # Повертаємо вже premium HTML, щоб у зібраних f-string цей емодзі не губився.
    return emoji_to_premium(symbol)


def _is_roulette_text_trigger(message: Message) -> bool:
    """
    Текстовий тригер для рулетки без слеша:
    - точно «рулетка» або «рулетки» (будь-який регістр)
    """
    if not message or not message.text:
        return False
    text = (message.text or "").strip().lower()
    if not text or text.startswith("/"):
        return False
    return text in ("рулетка", "рулетки")


def _menu_open_cooldown_left_sec(user_id: int) -> float:
    last = _menu_open_monotonic.get(int(user_id))
    if last is None:
        return 0.0
    return max(0.0, MENU_OPEN_COOLDOWN_SECONDS - (time.monotonic() - last))


def _touch_menu_open(user_id: int) -> None:
    _menu_open_monotonic[int(user_id)] = time.monotonic()


@dataclass
class _Session:
    bet: int | None = None
    bet_type: str | None = None
    awaiting_custom_amount: bool = False
    spin_in_progress: bool = False
    pending_contract_offer: bool = False
    # Після програшу VIP+: перекрут (ставка вже списана), без ліміту «раз на день»
    reroll_pack: tuple[int, str] | None = None
    # ID повідомлення-запиту «Введи суму ставки» — щоб прибрати його, коли суму введено.
    custom_prompt_msg_id: int | None = None


_sessions: dict[tuple[int, int], _Session] = {}

_auto_delete_tasks: dict[tuple[int, int], asyncio.Task] = {}

# Персистентний реєстр запланованих автовидалень — щоб вони переживали рестарт бота.
# Таймери живуть лише в пам'яті; без цього файлу повідомлення, заплановані на
# видалення менш ніж за 60с до рестарту, лишались би назавжди.
_PENDING_DELETE_FILE = Path(__file__).resolve().parent.parent / "roulette_pending_deletes.json"
_pending_deletes: dict[str, dict] = {}


def _pkey(chat_id: int, message_id: int) -> str:
    return f"{int(chat_id)}:{int(message_id)}"


def _persist_pending() -> None:
    try:
        _PENDING_DELETE_FILE.write_text(json.dumps(_pending_deletes), encoding="utf-8")
    except Exception:
        pass


def _pending_add(chat_id: int, message_id: int, delete_at: float) -> None:
    _pending_deletes[_pkey(chat_id, message_id)] = {
        "chat_id": int(chat_id), "message_id": int(message_id), "at": float(delete_at),
    }
    _persist_pending()


def _pending_remove(chat_id: int, message_id: int) -> None:
    if _pending_deletes.pop(_pkey(chat_id, message_id), None) is not None:
        _persist_pending()


def _cancel_autodelete(chat_id: int, message_id: int) -> None:
    key = (int(chat_id), int(message_id))
    t = _auto_delete_tasks.pop(key, None)
    if t and not t.done():
        try:
            t.cancel()
        except Exception:
            pass
    _pending_remove(chat_id, message_id)


async def roulette_startup_cleanup(bot: Bot) -> None:
    """Викликати при старті бота: дочистити повідомлення, чиї таймери автовидалення
    загинули під час попереднього рестарту."""
    global _pending_deletes
    try:
        raw = json.loads(_PENDING_DELETE_FILE.read_text(encoding="utf-8"))
        _pending_deletes = raw if isinstance(raw, dict) else {}
    except Exception:
        _pending_deletes = {}
    if not _pending_deletes:
        return
    now = time.time()
    for key, info in list(_pending_deletes.items()):
        try:
            cid = int(info["chat_id"]); mid = int(info["message_id"]); at = float(info.get("at", 0))
        except Exception:
            _pending_deletes.pop(key, None)
            continue
        delay = at - now
        if delay <= 1:
            try:
                await bot.delete_message(chat_id=cid, message_id=mid)
            except Exception:
                try:
                    await bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=None)
                except Exception:
                    pass
            _pending_deletes.pop(key, None)
        else:
            # Ще не час — перепланувати на залишок.
            _schedule_autodelete(bot, cid, mid, seconds=int(delay) + 1)
    _persist_pending()


def _schedule_autodelete(bot: Bot, chat_id: int, message_id: int, *, seconds: int = 60) -> None:
    # Скасовуємо попередній таймер для цього ж повідомлення, але НЕ чіпаємо реєстр
    # (його одразу перезапишемо нижче з новим часом).
    key = (int(chat_id), int(message_id))
    t = _auto_delete_tasks.pop(key, None)
    if t and not t.done():
        try:
            t.cancel()
        except Exception:
            pass
    _pending_add(chat_id, message_id, time.time() + max(1, int(seconds)))

    async def _delete_later():
        await asyncio.sleep(max(1, int(seconds)))
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            try:
                print(f"[roulette] autodelete failed chat_id={chat_id} msg_id={message_id}: {type(e).__name__}: {e}")
            except Exception:
                pass
            # Фолбек: хоча б прибрати клавіатуру, якщо видаляти не можна
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            except Exception:
                pass
        _auto_delete_tasks.pop((int(chat_id), int(message_id)), None)
        _pending_remove(chat_id, message_id)

    try:
        _auto_delete_tasks[(int(chat_id), int(message_id))] = asyncio.create_task(_delete_later())
    except Exception:
        pass


def _get_session(chat_id: int, user_id: int) -> _Session:
    key = (int(chat_id), int(user_id))
    s = _sessions.get(key)
    if not s:
        s = _Session()
        _sessions[key] = s
    return s


def _kb_entry(owner_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="+100", callback_data=f"roulette_bet:{owner_id}:100")
    b.button(text="+500", callback_data=f"roulette_bet:{owner_id}:500")
    b.button(text="+1000", callback_data=f"roulette_bet:{owner_id}:1000")
    b.button(text="Своя сума", callback_data=f"roulette_custom:{owner_id}")
    b.adjust(3, 1)
    return b.as_markup()


def _roulette_back_button(owner_id: int) -> InlineKeyboardButton:
    cid = custom_emoji_id_for_symbol("⬅️")
    if cid:
        return InlineKeyboardButton(
            text="Назад",
            callback_data=f"roulette_back:{owner_id}:entry",
            icon_custom_emoji_id=cid,
        )
    return InlineKeyboardButton(text="⬅️ Назад", callback_data=f"roulette_back:{owner_id}:entry")


def _kb_types(owner_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔴 Червоне - x2", callback_data=f"roulette_type:{owner_id}:red")
    b.button(text="⚫️ Чорне - x2", callback_data=f"roulette_type:{owner_id}:black")
    b.button(text="🎲 Рандом - x1.5", callback_data=f"roulette_type:{owner_id}:random")
    b.button(text="💎 Все або нічого - x5", callback_data=f"roulette_type:{owner_id}:allin")
    b.add(_roulette_back_button(owner_id))
    b.adjust(1)
    return b.as_markup()


def _kb_contract(owner_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    doc = custom_emoji_id_for_symbol("📜")
    qm = custom_emoji_id_for_symbol("❓")
    if doc:
        b.button(
            text="Прийняти",
            callback_data=f"roulette_contract:{owner_id}:accept",
            icon_custom_emoji_id=doc,
        )
    else:
        b.button(text="Прийняти", callback_data=f"roulette_contract:{owner_id}:accept")
    if qm:
        b.button(
            text="Відмовитись",
            callback_data=f"roulette_contract:{owner_id}:decline",
            icon_custom_emoji_id=qm,
        )
    else:
        b.button(text="Відмовитись", callback_data=f"roulette_contract:{owner_id}:decline")
    b.adjust(2)
    return b.as_markup()


def _now_utc_naive() -> datetime:
    return datetime.utcnow()


async def _roulette_actual_balance_loss(balance_before_spin: int, user_id: int) -> int:
    """Скільки лір реально знято з балансу від початку спіну (до страховки)."""
    current_balance = await get_balance_async(user_id)
    return max(0, int(balance_before_spin) - int(current_balance))


def _cooldown_remaining_text(profile: dict) -> str | None:
    cd = profile.get("cooldown_until")
    if not cd:
        return None
    try:
        remaining = cd.replace(tzinfo=None) - datetime.now()
    except Exception:
        return None
    if remaining.total_seconds() <= 0:
        return None
    mins = int(remaining.total_seconds() // 60)
    secs = int(remaining.total_seconds() % 60)
    if mins <= 0:
        return f"{secs}с"
    return f"{mins}хв {secs}с"


def _entry_text(balance: int, user_id: int, flair_html: str | None = None) -> str:
    # Показуємо лише інформаційно. Реальне нарахування VIP щоденного бонусу -
    # виконується окремим фоновим циклом при зміні дня (в run.py).
    head = (
        "🎰 <b>Рулетка</b>\n"
        "Тут удача вирішує більше, ніж ти.\n\n"
        f"💰 Баланс: <b>{balance}</b>💵\n"
        "Скільки готовий програти?"
    )
    if flair_html:
        head = f"{flair_html}\n\n{head}"
    return emoji_to_premium(head, skip_vip_badges=True)


async def _ensure_user_in_db(user) -> None:
    """Рулетка може викликатись без /start, тому гарантуємо рядок users."""
    if not user:
        return
    try:
        uid = int(user.id)
        tg_name = (getattr(user, "first_name", None) or "").strip() or None
        link = getattr(user, "username", None) or None
        def _upsert_user():
            exists = _db_fetchone_sync("SELECT 1 FROM users WHERE id = %s", (uid,)) is not None
            if not exists:
                _db_execute_sync(
                    "INSERT INTO users (id, tg_name, link, registered_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                    (uid, tg_name, link),
                )
                _db_commit_sync()
            else:
                _db_execute_sync("UPDATE users SET tg_name = %s, link = %s WHERE id = %s", (tg_name, link, uid))
                _db_commit_sync()
        await run_db_call_async(_upsert_user)
    except Exception:
        pass


@router_roulette.message(Command("roulette"))
async def roulette_cmd(message: Message, bot: Bot):
    if not message.from_user:
        return
    left = _menu_open_cooldown_left_sec(message.from_user.id)
    if left > 0:
        secs = max(1, math.ceil(left))
        try:
            await message.reply(
                emoji_to_premium(f"⏳ Зачекай <b>{secs}</b> с перед наступним викликом рулетки."),
                parse_mode="html",
            )
        except Exception:
            pass
        return
    # Прибираємо повідомлення з командою (/roulette або /roulette@bot), якщо є права.
    try:
        await message.delete()
    except Exception:
        pass
    await _open_roulette_menu(message, bot)


# NOTE:
# Не дублюємо /roulette через regex-fallback, бо це викликає подвійне відкриття меню
# (одночасно спрацьовують Command("roulette") і regexp-хендлер).


@router_roulette.message(F.text, F.func(_is_roulette_text_trigger))
async def roulette_text_trigger_cmd(message: Message, bot: Bot):
    """Тригер рулетки без /команди (наприклад: «Рулетка» / «Рулетки»)."""
    if not message.from_user:
        return
    left = _menu_open_cooldown_left_sec(message.from_user.id)
    if left > 0:
        secs = max(1, math.ceil(left))
        try:
            await message.reply(
                emoji_to_premium(f"⏳ Зачекай <b>{secs}</b> с перед наступним викликом рулетки."),
                parse_mode="html",
            )
        except Exception:
            pass
        return
    try:
        await message.delete()
    except Exception:
        pass
    await _open_roulette_menu(message, bot)


async def _open_roulette_menu(message: Message, bot: Bot):
    if not message.chat:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    await _ensure_user_in_db(message.from_user)
    await roulette_get_profile_async(user_id)  # ensure exists
    try:
        vb, tier_v = vip_mod.vip_try_daily_currency_bonus_with_tier(user_id)
        if vb > 0 and tier_v:
            await message.answer(
                emoji_to_premium(
                    vip_mod.vip_daily_bonus_notification_html(vb, tier_v)
                ),
                parse_mode="html",
            )
    except Exception:
        pass
    s = _get_session(chat_id, user_id)
    s.bet = None
    s.bet_type = None
    s.awaiting_custom_amount = False
    s.pending_contract_offer = False
    s.reroll_pack = None

    bal = await get_balance_async(user_id)
    flair = ""
    if message.chat.type != ChatType.PRIVATE and message.from_user:
        nick = message.from_user.full_name or message.from_user.first_name or ""
        flair = vip_mod.maybe_vip_context_flair_html(user_id, nick)
    entry_text = _entry_text(bal, user_id, flair or None)
    sent = await message.answer(
        entry_text,
        reply_markup=_kb_entry(user_id),
        parse_mode="html",
        protect_content=(message.chat.type == ChatType.PRIVATE),
    )
    if sent:
        _touch_menu_open(user_id)
    try:
        if sent:
            _schedule_autodelete(bot, chat_id, sent.message_id, seconds=60)
    except Exception:
        pass


def _parse_cb(data: str, prefix: str) -> tuple[int, str] | None:
    # prefix like "roulette_bet:" then "{owner_id}:..."
    if not data.startswith(prefix):
        return None
    rest = data[len(prefix) :]
    parts = rest.split(":", 1)
    try:
        owner_id = int(parts[0])
    except Exception:
        return None
    # Деякі колбеки можуть бути без “хвоста” (наприклад roulette_custom:<owner_id>)
    tail = parts[1] if len(parts) > 1 else ""
    return owner_id, tail


@router_roulette.callback_query(F.data.startswith("roulette_bet:"))
async def roulette_pick_bet(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    try:
        _cancel_autodelete(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    parsed = _parse_cb(callback.data or "", "roulette_bet:")
    if not parsed:
        await callback.answer()
        return
    owner_id, bet_str = parsed
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя рулетка.", show_alert=True)
        return

    chat_id = callback.message.chat.id if callback.message.chat else 0
    user_id = callback.from_user.id
    s = _get_session(chat_id, user_id)
    s.awaiting_custom_amount = False

    try:
        bet = int(bet_str)
    except Exception:
        await callback.answer("Некоректна ставка.", show_alert=True)
        return

    if bet < BET_MIN or bet > BET_MAX:
        await callback.answer("Ставка поза межами.", show_alert=True)
        return

    s.bet = bet
    await callback.message.edit_text(
        emoji_to_premium(
            "💰 <b>Вибір ставки</b>\n"
            f"Обрано: <b>{bet}</b>💵\n\n"
            "🎯 <b>На що ставимо?</b>"
        ),
        reply_markup=_kb_types(user_id),
        parse_mode="html",
    )
    try:
        _schedule_autodelete(callback.bot, callback.message.chat.id, callback.message.message_id, seconds=60)
    except Exception:
        pass
    await callback.answer()


@router_roulette.callback_query(F.data.startswith("roulette_custom:"))
async def roulette_custom_amount(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    try:
        _cancel_autodelete(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    parsed = _parse_cb(callback.data or "", "roulette_custom:")
    if not parsed:
        await callback.answer()
        return
    owner_id, _ = parsed
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя рулетка.", show_alert=True)
        return
    chat_id = callback.message.chat.id if callback.message.chat else 0
    user_id = callback.from_user.id
    s = _get_session(chat_id, user_id)
    s.awaiting_custom_amount = True
    # Щоб після перезапуску бота введення числа все одно спрацювало
    try:
        await roulette_update_profile_async(user_id, pending_custom_minutes=10, set_last_play_now=False)
    except Exception:
        pass
    await callback.message.edit_text(
        emoji_to_premium(
            "💰 <b>Вибір ставки</b>\n"
            "Введи суму ставки:\n"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[_roulette_back_button(user_id)]]
        ),
        parse_mode="html",
    )
    # Запам'ятовуємо запит, щоб прибрати його, коли гравець введе суму.
    s.custom_prompt_msg_id = callback.message.message_id
    try:
        _schedule_autodelete(callback.bot, callback.message.chat.id, callback.message.message_id, seconds=60)
    except Exception:
        pass
    await callback.answer()


@router_roulette.callback_query(F.data.startswith("roulette_back:"))
async def roulette_back(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    try:
        _cancel_autodelete(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    parsed = _parse_cb(callback.data or "", "roulette_back:")
    if not parsed:
        await callback.answer()
        return
    owner_id, where = parsed
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя рулетка.", show_alert=True)
        return
    chat_id = callback.message.chat.id if callback.message.chat else 0
    user_id = callback.from_user.id
    s = _get_session(chat_id, user_id)
    bal = await get_balance_async(user_id)

    if where == "entry":
        s.bet = None
        s.bet_type = None
        s.awaiting_custom_amount = False
        flair = ""
        if callback.message.chat and callback.message.chat.type != ChatType.PRIVATE and callback.from_user:
            nick = callback.from_user.full_name or callback.from_user.first_name or ""
            flair = vip_mod.maybe_vip_context_flair_html(user_id, nick)
        entry_text = _entry_text(bal, user_id, flair or None)
        await callback.message.edit_text(
            entry_text,
            reply_markup=_kb_entry(user_id),
            parse_mode="html",
        )
        try:
            _schedule_autodelete(callback.bot, callback.message.chat.id, callback.message.message_id, seconds=60)
        except Exception:
            pass
        await callback.answer()
        return

    await callback.answer()


@router_roulette.message(
    # Перехоплюємо тільки “валідну” суму для рулетки, щоб не заважати /construct_event (там часто числа типу 3–20)
    # Допустимо: 100..1000000000000
    F.text.regexp(r"^\s*(?:1000000000000|[1-9]\d{2,11})\s*$")
)
async def roulette_amount_input(message: Message):
    if not message.from_user or not message.text:
        return
    if not message.chat:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    # Перевіряємо очікування через БД (після перезапуску _sessions може зникнути).
    profile = None
    try:
        profile = await roulette_get_profile_async(user_id)
    except Exception:
        profile = None
    pending_custom_until = None if not profile else profile.get("pending_custom_until")
    pending_ok = False
    if pending_custom_until:
        try:
            pending_ok = pending_custom_until.replace(tzinfo=None) > datetime.now()
        except Exception:
            pending_ok = False

    s = _sessions.get((int(chat_id), int(user_id)))
    if not pending_ok and (not s or not s.awaiting_custom_amount):
        try:
            print(
                f"[roulette] amount input ignored: chat_id={chat_id} user_id={user_id} "
                f"s_exists={bool(s)} awaiting={getattr(s,'awaiting_custom_amount',None)} text={message.text!r}"
            )
        except Exception:
            pass
        return

    try:
        print(f"[roulette] amount input accepted: chat_id={chat_id} user_id={user_id} text={message.text!r}")
    except Exception:
        pass

    txt = (message.text or "").strip().replace(" ", "")
    try:
        bet = int(txt)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        hint = await message.answer("Введи число (наприклад 500).")
        try:
            if hint and message.chat:
                _schedule_autodelete(message.bot, message.chat.id, hint.message_id, seconds=30)
        except Exception:
            pass
        return

    if bet < BET_MIN or bet > BET_MAX:
        try:
            await message.delete()
        except Exception:
            pass
        hint = await message.answer(f"Ставка має бути від {BET_MIN} до {BET_MAX}.")
        try:
            if hint and message.chat:
                _schedule_autodelete(message.bot, message.chat.id, hint.message_id, seconds=30)
        except Exception:
            pass
        return

    if s:
        s.bet = bet
        s.awaiting_custom_amount = False
    try:
        await roulette_update_profile_async(user_id, clear_pending_custom=True)
    except Exception:
        pass
    # Автоочистка: прибираємо повідомлення гравця з введеною сумою, щоб не засмічувати чат.
    try:
        await message.delete()
    except Exception:
        pass
    # Прибираємо запит «Введи суму ставки» (з кнопкою «Назад»), щоб він не висів.
    if s and s.custom_prompt_msg_id and message.chat:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=s.custom_prompt_msg_id)
        except Exception:
            pass
        s.custom_prompt_msg_id = None
    sent = await message.answer(
        emoji_to_premium(
            "💰 <b>Вибір ставки</b>\n"
            f"Обрано: <b>{bet}</b>💵\n\n"
            "🎯 <b>На що ставимо?</b>"
        ),
        reply_markup=_kb_types(user_id),
        parse_mode="html",
        protect_content=(message.chat.type == ChatType.PRIVATE),
    )
    try:
        if sent and message.chat:
            _schedule_autodelete(message.bot, message.chat.id, sent.message_id, seconds=60)
    except Exception:
        pass


def _apply_anti_abuse(base_win_chance: float, profile: dict) -> float:
    win_streak = int(profile.get("win_streak") or 0)
    lose_streak = int(profile.get("lose_streak") or 0)

    # Анти-аб’юз: лише знижуємо шанс на довгих серіях виграшів; підвищувати не даємо.
    if win_streak >= 3:
        base_win_chance -= 0.08
    _ = lose_streak  # серія програшів більше не підвищує шанс виграшу

    # Кіт: -10% до шансів виграшу
    cat_until = profile.get("cat_debuff_until")
    if cat_until:
        try:
            if cat_until.replace(tzinfo=None) > datetime.now():
                base_win_chance -= 0.10
        except Exception:
            pass

    # Угода (прийняв): шанс зменшено, але множник зростає
    if profile.get("contract_penalty"):
        base_win_chance -= 0.10

    # обмеження
    if base_win_chance < 0.01:
        base_win_chance = 0.01
    if base_win_chance > 0.95:
        base_win_chance = 0.95
    return base_win_chance


def _pick_toxic_phrase(category: str) -> str:
    phrases = {
        "lose": [
            "Ти реально думав, що виграєш?",
            "Дякую за донат.",
            "Казино любить таких як ти. Постійно.",
            "Ти не програв - ти інвестував у чужий успіх.",
            "Спробуй ще раз. Нам подобається, як ти втрачаєш.",
        ],
        "small_win": [
            "О, дивись, щось випало. Не звикай.",
            "Це щоб ти не пішов.",
            "Казино підкинуло кістку.",
        ],
        "big_win": [
            "Тобі пощастило. Це ненадовго.",
            "Запам’ятай цей момент. Далі буде гірше.",
            "Вітаю. Тепер ти ціль.",
            "У тебе з’явились гроші. І вороги.",
        ],
        "buff": [
            "Цікаво, ти зрозумієш, що це було?",
            "Не радій завчасно.",
            "Іноді подарунки - це пастка.",
        ],
        "debuff": [
            "Ти це ще відчуєш.",
            "Казино нічого не забуває.",
            "Це був не програш. Це початок.",
        ],
        "contract": [
            "Підписав? Ну-ну.",
            "Ти ж не думав, що це безкоштовно?",
            "Гарна помилка.",
        ],
    }
    arr = phrases.get(category) or ["..."]
    return random.choice(arr)


async def _safe_edit_or_send(
    bot: Bot,
    *,
    message: Message | None,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    if not text:
        return None
    try:
        if message:
            await message.edit_text(text, parse_mode="html", reply_markup=reply_markup)
            return message
    except Exception:
        pass
    try:
        sent = await bot.send_message(chat_id=chat_id, text=text, parse_mode="html", reply_markup=reply_markup)
        return sent
    except Exception:
        pass
    return None


async def _typing_result_animation(
    bot: Bot, *, message: Message | None, chat_id: int
) -> Message | None:
    """
    Коротка анімація "печатного тексту" перед результатом рулетки.
    Працює як стрімінг: серія нових повідомлень із заміною попереднього кадру.
    """
    l1 = "Кулька крутиться…"
    l2 = "Фішки на столі…"
    l3 = "Хтось уже програв. Можливо, це ти."
    # Менше кадрів, щоб уникати flood control у групах.
    frames = [
        "🎰\n" + l1,
        "🎰\n" + l1 + "\n" + l2 + "\n" + l3,
    ]
    target_msg: Message | None = message
    target_msg_id: int | None = message.message_id if message else None
    # Анімація має бути короткою. Якщо Telegram дає великий floodwait,
    # не блокуємо видачу результату на хвилини - просто завершуємо анімацію.
    started_at = time.monotonic()
    max_anim_seconds = 2.2
    for frame in frames:
        if (time.monotonic() - started_at) > max_anim_seconds:
            break
        try:
            if target_msg_id is not None:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=target_msg_id,
                    text=emoji_to_premium(frame),
                    parse_mode="html",
                )
            else:
                sent = await bot.send_message(
                    chat_id=chat_id,
                    text=emoji_to_premium(frame),
                    parse_mode="html",
                )
                target_msg = sent
                target_msg_id = sent.message_id
        except TelegramRetryAfter as e:
            # Якщо Telegram просить великий floodwait, не зависаємо на анімації.
            retry_s = float(getattr(e, "retry_after", 0) or 0)
            if retry_s > 2.0:
                break
            await asyncio.sleep(min(0.8, max(0.05, retry_s)))
            try:
                if target_msg_id is not None:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=target_msg_id,
                        text=emoji_to_premium(frame),
                        parse_mode="html",
                    )
                else:
                    sent = await bot.send_message(
                        chat_id=chat_id,
                        text=emoji_to_premium(frame),
                        parse_mode="html",
                    )
                    target_msg = sent
                    target_msg_id = sent.message_id
            except Exception:
                pass
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                pass
        except Exception:
            pass
        # Пауза між кадрами для "стріму" без спаму edit_message.x
        await asyncio.sleep(SPIN_STREAM_FRAME_DELAY)
    return target_msg


async def _reroll_single_outcome(user_id: int, bet: int, bet_type: str) -> tuple[str, int]:
    """
    Другий шанс після програшу (ставка вже була списана).
    Повертає (текст HTML, скільки додати на баланс: 0 або повний payout при виграші).
    """
    profile = await roulette_get_profile_async(user_id)
    contract_mult = max(1, int(profile.get("contract_multiplier_next") or 1))
    tier = vip_mod.active_vip_tier(user_id)
    mul = vip_mod.win_bonus_multiplier(tier)
    bias = 0.0

    if bet_type in ("red", "black"):
        base_color_chance = _color_base_chance(user_id, bet, bet_type)
        if _is_roulette_owner(user_id):
            win_chance = base_color_chance
        else:
            win_chance = min(0.88, _apply_anti_abuse(base_color_chance, profile) + bias)
        is_win = random.random() < win_chance
        if is_win:
            win = int(round(bet * 2 * contract_mult * mul))
            payout = bet + win
            await roulette_update_profile_async(
                user_id,
                win_streak=int(profile["win_streak"]) + 1,
                lose_streak=0,
                contract_multiplier_next=1,
                contract_penalty=False,
                debt_multiplier=False,
            )
            res = emoji_to_premium(
                f"🔁 <b>Перекрут!</b>\n"
                f"{'🔴' if bet_type == 'red' else '⚫️'}\n"
                f"Цього разу зайшло.\n+{win}💵"
            )
            return res, payout
        res = emoji_to_premium("🔁 Перекрут не виправив результат.\nПотрібен новий задум.")
        return res, 0

    if bet_type == "random":
        r = random.random()
        if _is_roulette_owner(user_id):
            if r < ROULETTE_OWNER_WIN_CHANCE:
                small_win = int(round(bet * 0.5 * contract_mult * mul))
                await roulette_update_profile_async(user_id, win_streak=int(profile["win_streak"]) + 1, lose_streak=0, contract_multiplier_next=1, contract_penalty=False)
                res = emoji_to_premium(f"🔁 Перекрут вдалий.\n+{small_win}💵")
                return res, bet + small_win
            res = emoji_to_premium("🔁 Перекрут не допоміг.\nМінус залишається.")
            return res, 0
        if _random_profit_allowed(user_id, bet):
            if r < 0.30:
                await roulette_update_profile_async(user_id, win_streak=0, lose_streak=0, contract_multiplier_next=1, contract_penalty=False)
                res = emoji_to_premium("🔁 Перекрут: кості відпустили.\n+0💵 (ставка повернена)")
                return res, bet
            if r < 0.80:
                small_win = int(round(bet * 0.5 * contract_mult * mul))
                await roulette_update_profile_async(user_id, win_streak=int(profile["win_streak"]) + 1, lose_streak=0, contract_multiplier_next=1, contract_penalty=False)
                res = emoji_to_premium(f"🔁 Перекрут вдалий.\n+{small_win}💵")
                return res, bet + small_win
            res = emoji_to_premium("🔁 Перекрут не допоміг.\nМінус залишається.")
            return res, 0
        # Велика ставка (не власник): без прибутку — максимум повернення.
        if r < 0.30:
            await roulette_update_profile_async(user_id, win_streak=0, lose_streak=0, contract_multiplier_next=1, contract_penalty=False)
            res = emoji_to_premium("🔁 Перекрут: кості відпустили.\n+0💵 (ставка повернена)")
            return res, bet
        res = emoji_to_premium("🔁 Перекрут не допоміг.\nМінус залишається.")
        return res, 0

    # all-in (×5)
    _allin_base = _allin_base_chance(user_id, bet)
    if _is_roulette_owner(user_id):
        win_chance = _allin_base
    else:
        win_chance = min(0.78, _apply_anti_abuse(_allin_base, profile) + bias)
    is_win = random.random() < win_chance
    if is_win:
        big_win = int(round(bet * 5 * contract_mult * mul))
        payout = bet + big_win
        await roulette_update_profile_async(
            user_id,
            win_streak=int(profile["win_streak"]) + 1,
            lose_streak=0,
            contract_multiplier_next=1,
            contract_penalty=False,
            debt_multiplier=False,
        )
        res = emoji_to_premium(f"🔁 Перекрут! Все або нічого зайшло.\n+{big_win}💵")
        return res, payout
    res = emoji_to_premium("🔁 Перекрут не спрацював.\nУдачі наступного разу.")
    return res, 0


def _loss_emoji_for_bet_type(bet_type: str) -> str:
    if bet_type == "red":
        return "🔴"
    if bet_type == "black":
        return "⚫️"
    if bet_type == "random":
        return "🎲"
    return "🎰"


def _vip_upsell_loss_message_and_button(
    bet_type: str, net_loss: int, lose_streak: int
) -> tuple[str, str]:
    """
    Без VIP: короткий текст продажу + підпис кнопки.
    lose_streak - після оновлення профілю (рахується поточна серія програшів).
    """
    if lose_streak >= 3:
        txt = (
            "💀\n"
            "Тебе сьогодні явно не люблять.\n"
            f"-{net_loss}💵\n\n"
            "⚒️ VIP трохи вирівнює такі дні."
        )
        return emoji_to_premium(txt), "⚒️ Випробувати вдачу"
    head = _loss_emoji_for_bet_type(bet_type)
    txt = (
        f"{head}\n"
        "Не твій день.\n"
        f"-{net_loss}💵\n\n"
        "⚒️ З VIP ти б втратив менше."
    )
    return emoji_to_premium(txt), "⚒️ Спробувати VIP"


def _hypothetical_net_win_with_vip(bet: int, contract_mult: int, coef: float) -> int:
    """Чистий виграш при тому ж коефіцієнті гри, якби діяв множник VIP (без VIP+)."""
    m = vip_mod.win_bonus_multiplier("vip")
    return int(round(bet * coef * contract_mult * m))


def _vip_upsell_win_message(actual_win: int, total_if_vip: int) -> str:
    """total_if_vip - повна сума виграшу з VIP, а не лише «зверху»."""
    return emoji_to_premium(
        "💰\n"
        "Непогано.\n"
        f"+{actual_win}💵\n\n"
        f"⚒️ З VIP це було б {total_if_vip}💵."
    )


def _vip_upsell_win_markup() -> InlineKeyboardMarkup:
    uxb = InlineKeyboardBuilder()
    uxb.button(text="⚒️ Забрати більше", callback_data="vip_upsell:shop")
    uxb.adjust(1)
    return uxb.as_markup()


def _vip_subscriber_win_bonus_line(
    tier: str | None,
    bet: int,
    contract_mult: int,
    mul: float,
    coef: float,
    actual_win: int,
) -> str:
    """
    Додаток до тексту виграшу для VIP/VIP+: скільки 💵 дає множник тарифу (порівняно з mul=1.0).
    coef: 2 (червоне/чорне), 0.5 (рандом), 5 (все або нічого).
    """
    if tier not in ("vip", "vip_plus") or mul <= 1.0:
        return ""
    base_win = int(round(bet * coef * contract_mult * 1.0))
    extra = max(0, int(actual_win) - base_win)
    if extra <= 0:
        return ""
    label = "VIP+" if tier == "vip_plus" else "VIP"
    em = _vip_display_emoji(tier)
    return (
        f"\n\n{em} <b>{label}:</b> +{extra}💵 додано твоїм тарифом до базового виграшу."
    )


def _post_loss_keyboard(
    owner_id: int,
    user_id: int,
    tier: str | None,
    bet: int,
    bet_type: str,
    s: _Session,
    upsell_label: str = "⚒️ Спробувати VIP",
) -> InlineKeyboardMarkup | None:
    """Кнопки після програшу: перекрут для VIP+, upsell для без підписки."""
    b = InlineKeyboardBuilder()
    placed = False
    if tier == "vip_plus":
        # Не ховаємо кнопку - ліміт перевіряється в roulette_reroll_cb.
        s.reroll_pack = (bet, bet_type)
        rr = custom_emoji_id_for_symbol("🔁") or custom_emoji_id_for_symbol("🔄")
        if rr:
            b.button(
                text="Перекрут (VIP+)",
                callback_data=f"roulette_reroll:{owner_id}",
                icon_custom_emoji_id=rr,
            )
        else:
            b.button(
                text="🔁 Перекрут (VIP+)",
                callback_data=f"roulette_reroll:{owner_id}",
            )
        placed = True
    if tier is None:
        b.button(text=upsell_label, callback_data="vip_upsell:shop")
        placed = True
    if not placed:
        return None
    b.adjust(1)
    return b.as_markup()


async def _run_event(
    bot: Bot, user_id: int, bet: int, tier: str | None = None
) -> tuple[str, int, InlineKeyboardMarkup | None]:
    """
    Повертає (text, balance_delta, markup).
    """
    roll = random.random()

    # Події: 5 варіантів
    # 0.00–0.22 🚓 облава
    # 0.22–0.36 🎩 бонус (вужче — рідше «безкоштовний» плюс)
    # 0.36–0.58 🐈‍⬛ кіт
    # 0.58–0.78 💀 борг
    # 0.78–1.00 🤝 угода
    if roll < 0.22:
        penalty = max(50, int(bet * 0.35))
        text = emoji_to_premium(
            "🚔 Казино накрили.\n"
            "🚨 Тривога по всіх столах.\n"
            "Ти не встиг вийти.\n\n"
            f"-{bet}💵\n"
            f"-{penalty}💵"
        )
        return text, -(bet + penalty), None
    if roll < 0.36:
        m = vip_mod.win_bonus_multiplier(tier)
        bonus = max(50, int(round(bet * 0.25 * m)))
        await roulette_update_profile_async(user_id, set_last_play_now=True)
        text = emoji_to_premium(
            "📈 Хтось залишив для тебе фішки.\n\n"
            f"+{bonus}💵\n"
            f"<i>{_pick_toxic_phrase('buff')}</i>"
        )
        return text, bonus, None
    if roll < 0.58:
        await roulette_update_profile_async(user_id, cat_debuff_minutes=60, set_last_play_now=True)
        text = emoji_to_premium(
            "Кіт перейшов дорогу.\n"
            "Наступна ставка буде менш щасливою.\n\n"
            f"<i>{_pick_toxic_phrase('debuff')}</i>"
        )
        return text, 0, None
    if roll < 0.78:
        await roulette_update_profile_async(user_id, debt_multiplier=True, set_last_play_now=True)
        text = emoji_to_premium(
            "Ти граєш у мінус.\n"
            "Наступний програш буде х2.\n\n"
            f"<i>{_pick_toxic_phrase('debuff')}</i>"
        )
        return text, 0, None

    text = emoji_to_premium(
        "🧩 Тобі пропонують угоду."
    )
    return text, 0, _kb_contract(user_id)


@router_roulette.callback_query(F.data.startswith("roulette_contract:"))
async def roulette_contract_decision(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    try:
        _cancel_autodelete(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    parsed = _parse_cb(callback.data or "", "roulette_contract:")
    if not parsed:
        await callback.answer()
        return
    owner_id, decision = parsed
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя рулетка.", show_alert=True)
        return
    chat_id = callback.message.chat.id if callback.message.chat else 0
    user_id = callback.from_user.id
    await _ensure_user_in_db(callback.from_user)
    s = _get_session(chat_id, user_id)
    if not s.pending_contract_offer:
        await callback.answer("Угоди вже немає.", show_alert=True)
        return

    s.pending_contract_offer = False

    if decision == "accept":
        await roulette_update_profile_async(user_id, contract_multiplier_next=3, contract_penalty=True, set_last_play_now=True)
        text = emoji_to_premium(
            "🤝 <b>(прийняв)</b>\n"
            "Наступний виграш x3\n\n"
            f"<i>{_pick_toxic_phrase('contract')}</i>"
        )
    else:
        text = emoji_to_premium(
            "🤝 <b>(відмовився)</b>\n"
            "Тут безкоштовно нічого не дають"
        )
    if callback.message:
        try:
            await callback.message.edit_text(text, parse_mode="html")
        except Exception:
            pass
    await callback.answer()


@router_roulette.callback_query(F.data.startswith("roulette_reroll:"))
async def roulette_reroll_cb(callback: CallbackQuery, bot: Bot):
    if not callback.from_user or not callback.message:
        return
    try:
        _cancel_autodelete(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    parsed = _parse_cb(callback.data or "", "roulette_reroll:")
    if not parsed:
        await callback.answer()
        return
    owner_id, _ = parsed
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя рулетка.", show_alert=True)
        return
    chat_id = callback.message.chat.id if callback.message.chat else 0
    user_id = callback.from_user.id
    s = _get_session(chat_id, user_id)
    pack = s.reroll_pack
    if not pack:
        await callback.answer("Перекрут недоступний.", show_alert=True)
        return
    if vip_mod.active_vip_tier(user_id) != "vip_plus":
        await callback.answer("Перекрут лише з підпискою VIP+.", show_alert=True)
        return
    bet, bet_type = pack[0], pack[1]

    # VIP+ має добовий ліміт перекрута (Київ).
    try:
        can_consume = vip_mod.roulette_vip_reroll_consume(user_id)
    except Exception as e:
        try:
            print(f"[roulette] reroll consume failed: {type(e).__name__}: {e}")
        except Exception:
            pass
        can_consume = False

    if not can_consume:
        # Щоб користувач не міг повторно тикати ту саму кнопку перекрута.
        s.reroll_pack = None
        try:
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer("Ліміт перекрута використано. Спробуй завтра.", show_alert=True)
        return

    s.reroll_pack = None
    html, payout = await _reroll_single_outcome(user_id, bet, bet_type)
    if payout > 0:
        await add_balance_to_user_async(user_id, payout)
    await callback.answer()
    m = await _safe_edit_or_send(bot, message=callback.message, chat_id=chat_id, text=html, reply_markup=None)
    if m:
        _schedule_autodelete(bot, chat_id, m.message_id, seconds=60)


@router_roulette.callback_query(F.data.startswith("roulette_type:"))
async def roulette_spin(callback: CallbackQuery, bot: Bot):
    if not callback.from_user or not callback.message:
        return
    try:
        _cancel_autodelete(callback.message.chat.id, callback.message.message_id)
    except Exception:
        pass
    parsed = _parse_cb(callback.data or "", "roulette_type:")
    if not parsed:
        await callback.answer()
        return
    owner_id, bet_type = parsed
    if callback.from_user.id != owner_id:
        await callback.answer("Це не твоя рулетка.", show_alert=True)
        return
    chat_id = callback.message.chat.id if callback.message.chat else 0
    user_id = callback.from_user.id
    await _ensure_user_in_db(callback.from_user)
    # Анти-спам: короткий тайм-аут між спінами.
    try:
        profile = await roulette_get_profile_async(user_id)
        rem = _cooldown_remaining_text(profile)
        if rem:
            await callback.answer(f"Зачекай {rem} перед наступним спіном.", show_alert=True)
            return
    except Exception:
        pass
    s = _get_session(chat_id, user_id)
    if not s.bet:
        await callback.answer("Спочатку обери ставку.", show_alert=True)
        return
    if s.spin_in_progress:
        await callback.answer("Спін уже обробляється, зачекай кілька секунд.", show_alert=True)
        return

    s.bet_type = bet_type
    s.reroll_pack = None
    s.spin_in_progress = True
    bet_deducted = False
    bet = int(s.bet)
    try:
        balance = await get_balance_async(user_id)
        if balance < bet:
            await callback.answer("Недостатньо грошей.", show_alert=True)
            return

        balance_before_spin = balance

        if not await deduct_balance_async(user_id, bet):
            await callback.answer("Не вдалося списати ставку.", show_alert=True)
            return
        bet_deducted = True

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer()
        target_message = await _typing_result_animation(
            bot,
            message=callback.message,
            chat_id=chat_id,
        ) or callback.message
        # Короткий КД 5 сек між спінами + фіксація активності.
        try:
            def _set_spin_cooldown():
                _db_execute_sync(
                    """
                    UPDATE roulette_profiles
                    SET last_play_at = CURRENT_TIMESTAMP,
                        cooldown_until = CURRENT_TIMESTAMP + (%s || ' seconds')::interval
                    WHERE user_id = %s
                    """,
                    (SPIN_TIMEOUT_SECONDS, user_id),
                )
                _db_commit_sync()
            await run_db_call_async(_set_spin_cooldown)
        except Exception:
            await roulette_update_profile_async(user_id, set_last_play_now=True)

        tier = vip_mod.active_vip_tier(user_id)
        if random.random() < 0.09:
            text, delta, markup = await _run_event(bot, user_id, bet, tier)
            if delta != 0:
                if delta > 0:
                    await add_balance_to_user_async(user_id, delta)
                else:
                    extra_loss = -delta - bet
                    if extra_loss > 0:
                        await deduct_balance_async(user_id, extra_loss)
            if text:
                if markup is not None:
                    s.pending_contract_offer = True
                elif delta < 0:
                    actual_loss_ev = await _roulette_actual_balance_loss(balance_before_spin, user_id)
                    ref = vip_mod.roulette_insurance_consume_and_refund(
                        user_id, tier, actual_loss_ev
                    )
                    if ref:
                        await add_balance_to_user_async(user_id, ref)
                        text = f"{text}\n\n{_vip_display_emoji(tier)} <b>VIP-страховка:</b> +{ref}💵"
                    if tier is None and actual_loss_ev >= max(1000, bet * 5):
                        text = f"{text}\n\n⚒️ З VIP частину могли б повернути (страховка)."
                    markup = _post_loss_keyboard(owner_id, user_id, tier, bet, bet_type, s)
                elif delta > 0 and tier is None:
                    vip_m = vip_mod.win_bonus_multiplier("vip")
                    total_if_vip = max(0, int(round(delta * vip_m)))
                    text = f"{text}\n\n⚒️ З VIP це було б {total_if_vip}💵."
                    ukb = InlineKeyboardBuilder()
                    ukb.button(text="⚒️ Забрати більше", callback_data="vip_upsell:shop")
                    ukb.adjust(1)
                    markup = ukb.as_markup()
                m = await _safe_edit_or_send(
                    bot,
                    message=target_message,
                    chat_id=chat_id,
                    text=text,
                    reply_markup=markup,
                )
                if m:
                    _schedule_autodelete(bot, chat_id, m.message_id, seconds=60)
                    try:
                        await vip_mod.maybe_social_vip_ping(bot, chat_id, callback.from_user, tier)
                    except Exception:
                        pass
                return
            m = await _safe_edit_or_send(
                bot,
                message=target_message,
                chat_id=chat_id,
                text=emoji_to_premium("🎭 Подія вже сталась."),
            )
            if m:
                _schedule_autodelete(bot, chat_id, m.message_id, seconds=60)
            return

        profile = await roulette_get_profile_async(user_id)
        contract_mult = int(profile.get("contract_multiplier_next") or 1)
        if contract_mult < 1:
            contract_mult = 1

        mul = vip_mod.win_bonus_multiplier(tier)
        spin_mk: InlineKeyboardMarkup | None = None

        if bet_type in ("red", "black"):
            base_color_chance = _color_base_chance(user_id, bet, bet_type)
            # Власникам — рівно фіксований шанс, без анти-аб'юзу.
            win_chance = base_color_chance if _is_roulette_owner(user_id) else _apply_anti_abuse(base_color_chance, profile)
            is_win = random.random() < win_chance
            if is_win:
                # Ставка списується на старті, тому при виграші повертаємо ставку + чистий виграш.
                win = int(round(bet * 2 * contract_mult * mul))
                payout = bet + win
                await add_balance_to_user_async(user_id, payout)
                await roulette_update_profile_async(
                    user_id,
                    win_streak=int(profile["win_streak"]) + 1,
                    lose_streak=0,
                    contract_multiplier_next=1,
                    contract_penalty=False,
                )
                if tier is None:
                    win_if_vip = _hypothetical_net_win_with_vip(bet, contract_mult, 2.0)
                    res = _vip_upsell_win_message(win, win_if_vip)
                    spin_mk = _vip_upsell_win_markup()
                else:
                    vip_extra = _vip_subscriber_win_bonus_line(
                        tier, bet, contract_mult, mul, 2.0, win
                    )
                    res = emoji_to_premium(
                        f"{'🔴' if bet_type == 'red' else '⚫️'}\n"
                        "Сьогодні тобі щастить.\n"
                        "🎯 Влучний вибір.\n"
                        f"+{win}💵\n\n"
                        f"<i>{_pick_toxic_phrase('small_win' if contract_mult == 1 else 'big_win')}</i>"
                        f"{vip_extra}"
                    )
                    spin_mk = None
            else:
                lose_mult = 2 if profile.get("debt_multiplier") else 1
                extra_loss = bet * (lose_mult - 1)
                if extra_loss > 0:
                    await deduct_balance_async(user_id, extra_loss)
                await roulette_update_profile_async(
                    user_id,
                    win_streak=0,
                    lose_streak=int(profile["lose_streak"]) + 1,
                    debt_multiplier=False,
                    contract_multiplier_next=1,
                    contract_penalty=False,
                )
                net_loss_rb = bet * lose_mult
                actual_loss_rb = await _roulette_actual_balance_loss(balance_before_spin, user_id)
                ref = vip_mod.roulette_insurance_consume_and_refund(
                    user_id, tier, actual_loss_rb
                )
                if tier is None:
                    ls = int((await roulette_get_profile_async(user_id))["lose_streak"])
                    res, upsell_btn = _vip_upsell_loss_message_and_button(
                        bet_type, net_loss_rb, ls
                    )
                    if ref:
                        await add_balance_to_user_async(user_id, ref)
                        res = f"{res}\n\n{_vip_display_emoji(tier)} <b>VIP-страховка:</b> +{ref}💵"
                    spin_mk = _post_loss_keyboard(
                        owner_id, user_id, tier, bet, bet_type, s, upsell_label=upsell_btn
                    )
                else:
                    res = emoji_to_premium(
                        f"{'🔴' if bet_type == 'red' else '⚫️'}\n"
                        "Не твій день.\n"
                        "❌ Ставка не зайшла.\n"
                        f"-{net_loss_rb}💵\n\n"
                        f"<i>{_pick_toxic_phrase('lose')}</i>"
                    )
                    if ref:
                        await add_balance_to_user_async(user_id, ref)
                        res = f"{res}\n\n{_vip_display_emoji(tier)} <b>VIP-страховка:</b> +{ref}💵"
                    spin_mk = _post_loss_keyboard(owner_id, user_id, tier, bet, bet_type, s)
        elif bet_type == "random":
            r = random.random()
            if _is_roulette_owner(user_id):
                # Власник: 55% виграш, інакше програш.
                _rnd_refund = False
                _rnd_win = r < ROULETTE_OWNER_WIN_CHANCE
            elif _random_profit_allowed(user_id, bet):
                # Нормальний рандом (ставка ≤ порогу): 10% повернення, ~78% невеликий виграш, решта програш.
                _rnd_refund = r < 0.10
                _rnd_win = (not _rnd_refund) and r < 0.88
            else:
                # Урізаний рандом (велика ставка): лише повернення або програш, без прибутку.
                _rnd_refund = r < 0.10
                _rnd_win = False

            if _rnd_refund:
                await add_balance_to_user_async(user_id, bet)
                await roulette_update_profile_async(user_id, win_streak=0, lose_streak=0, contract_multiplier_next=1, contract_penalty=False)
                res = emoji_to_premium("🎲\nКазино не любить жадібних.\n+0💵")
            elif _rnd_win:
                small_win = int(round(bet * 0.5 * contract_mult * mul))
                await add_balance_to_user_async(user_id, bet + small_win)
                await roulette_update_profile_async(
                    user_id,
                    win_streak=int(profile["win_streak"]) + 1,
                    lose_streak=0,
                    contract_multiplier_next=1,
                    contract_penalty=False,
                )
                if tier is None:
                    win_if_vip = _hypothetical_net_win_with_vip(bet, contract_mult, 0.5)
                    res = _vip_upsell_win_message(small_win, win_if_vip)
                    spin_mk = _vip_upsell_win_markup()
                else:
                    vip_extra = _vip_subscriber_win_bonus_line(
                        tier, bet, contract_mult, mul, 0.5, small_win
                    )
                    res = emoji_to_premium(
                        "🎲\n"
                        "Казино не любить жадібних.\n"
                        f"+{small_win}💵\n\n"
                        f"<i>{_pick_toxic_phrase('small_win')}</i>"
                        f"{vip_extra}"
                    )
                    spin_mk = None
            else:
                lose_mult = 2 if profile.get("debt_multiplier") else 1
                extra_loss = bet * (lose_mult - 1)
                if extra_loss > 0:
                    await deduct_balance_async(user_id, extra_loss)
                await roulette_update_profile_async(
                    user_id,
                    win_streak=0,
                    lose_streak=int(profile["lose_streak"]) + 1,
                    debt_multiplier=False,
                    contract_multiplier_next=1,
                    contract_penalty=False,
                )
                net_loss_rn = bet * lose_mult
                actual_loss_rn = await _roulette_actual_balance_loss(balance_before_spin, user_id)
                ref = vip_mod.roulette_insurance_consume_and_refund(
                    user_id, tier, actual_loss_rn
                )
                if tier is None:
                    ls = int((await roulette_get_profile_async(user_id))["lose_streak"])
                    res, upsell_btn = _vip_upsell_loss_message_and_button(
                        bet_type, net_loss_rn, ls
                    )
                    if ref:
                        await add_balance_to_user_async(user_id, ref)
                        res = f"{res}\n\n{_vip_display_emoji(tier)} <b>VIP-страховка:</b> +{ref}💵"
                    spin_mk = _post_loss_keyboard(
                        owner_id, user_id, tier, bet, bet_type, s, upsell_label=upsell_btn
                    )
                else:
                    res = emoji_to_premium(
                        "🎲\n"
                        "Казино не любить жадібних.\n"
                        "❌ Мінус по кишені.\n"
                        f"-{net_loss_rn}💵\n\n"
                        f"<i>{_pick_toxic_phrase('lose')}</i>"
                    )
                    if ref:
                        await add_balance_to_user_async(user_id, ref)
                        res = f"{res}\n\n{_vip_display_emoji(tier)} <b>VIP-страховка:</b> +{ref}💵"
                    spin_mk = _post_loss_keyboard(owner_id, user_id, tier, bet, bet_type, s)
        else:
            allin_base = _allin_base_chance(user_id, bet)
            win_chance = allin_base if _is_roulette_owner(user_id) else _apply_anti_abuse(allin_base, profile)
            is_win = random.random() < win_chance
            if is_win:
                # Аналогічно: повертаємо ставку + чистий виграш.
                big_win = int(round(bet * 5 * contract_mult * mul))
                payout = bet + big_win
                await add_balance_to_user_async(user_id, payout)
                await roulette_update_profile_async(
                    user_id,
                    win_streak=int(profile["win_streak"]) + 1,
                    lose_streak=0,
                    contract_multiplier_next=1,
                    contract_penalty=False,
                )
                if tier is None:
                    win_if_vip = _hypothetical_net_win_with_vip(bet, contract_mult, 5.0)
                    res = _vip_upsell_win_message(big_win, win_if_vip)
                    spin_mk = _vip_upsell_win_markup()
                else:
                    vip_extra = _vip_subscriber_win_bonus_line(
                        tier, bet, contract_mult, mul, 5.0, big_win
                    )
                    res = emoji_to_premium(
                        "💎\n"
                        "Ти або геній… або це останній раз.\n"
                        f"+{big_win}💵\n\n"
                        f"<i>{_pick_toxic_phrase('big_win')}</i>"
                        f"{vip_extra}"
                    )
                    spin_mk = None
            else:
                lose_mult = 2 if profile.get("debt_multiplier") else 1
                extra_loss = bet * (lose_mult - 1)
                if extra_loss > 0:
                    await deduct_balance_async(user_id, extra_loss)
                await roulette_update_profile_async(
                    user_id,
                    win_streak=0,
                    lose_streak=int(profile["lose_streak"]) + 1,
                    debt_multiplier=False,
                    contract_multiplier_next=1,
                    contract_penalty=False,
                )
                net_loss_ai = bet * lose_mult
                actual_loss_ai = await _roulette_actual_balance_loss(balance_before_spin, user_id)
                ref = vip_mod.roulette_insurance_consume_and_refund(
                    user_id, tier, actual_loss_ai
                )
                if tier is None:
                    ls = int((await roulette_get_profile_async(user_id))["lose_streak"])
                    res, upsell_btn = _vip_upsell_loss_message_and_button(
                        bet_type, net_loss_ai, ls
                    )
                    if ref:
                        await add_balance_to_user_async(user_id, ref)
                        res = f"{res}\n\n{_vip_display_emoji(tier)} <b>VIP-страховка:</b> +{ref}💵"
                    spin_mk = _post_loss_keyboard(
                        owner_id, user_id, tier, bet, bet_type, s, upsell_label=upsell_btn
                    )
                else:
                    res = emoji_to_premium(
                        "💎\n"
                        "Не твій день.\n"
                        f"-{net_loss_ai}💵\n\n"
                        f"<i>{_pick_toxic_phrase('lose')}</i>"
                    )
                    if ref:
                        await add_balance_to_user_async(user_id, ref)
                        res = f"{res}\n\n{_vip_display_emoji(tier)} <b>VIP-страховка:</b> +{ref}💵"
                    spin_mk = _post_loss_keyboard(owner_id, user_id, tier, bet, bet_type, s)

        m = await _safe_edit_or_send(
            bot,
            message=target_message,
            chat_id=chat_id,
            text=res,
            reply_markup=spin_mk,
        )
        if m:
            _schedule_autodelete(bot, chat_id, m.message_id, seconds=60)
            try:
                await vip_mod.maybe_social_vip_ping(bot, chat_id, callback.from_user, tier)
            except Exception:
                pass
    except Exception as e:
        # fallback: повернути ставку, якщо ми її вже списали, і показати помилку
        try:
            if bet_deducted:
                await add_balance_to_user_async(user_id, bet)
        except Exception:
            pass
        try:
            print(f"[roulette] error: {type(e).__name__}: {e}")
        except Exception:
            pass
        m = await _safe_edit_or_send(
            bot,
            message=callback.message,
            chat_id=chat_id,
            text=emoji_to_premium("🎰 Помилка рулетки. Спробуй ще раз через хвилинку."),
        )
        if m:
            _schedule_autodelete(bot, chat_id, m.message_id, seconds=60)
    finally:
        s.spin_in_progress = False

