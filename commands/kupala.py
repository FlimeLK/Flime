# -*- coding: utf-8 -*-
"""
Сезонний івент «Купальська ніч» — Фаза 2: економіка та крафт.

Хаб івенту (/kupala) доступний лише коли івент активний (вмикається в /capone_admin).
Складники:
  • «Похід до лісу» — раз на 24 год: завжди 1–2 лимони + 30% шанс на гілочку папороті.
  • Крафт вінків із лимонів/папороті (вінки → бафи, ефекти яких вмикаються у Фазі 3).
  • Інвентар івенту.

Зберігання:
  • Лимони — users.marigolds (через commands.marigolds).
  • Папороть, вінки — таблиця kupala_inventory (item_id → quantity).
  • Кулдаун лісу — kupala_player.forest_trip_at.
"""

import random
import os
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType

from database.database import run_db_call_async
import database.database as _db  # «живі» посилання cursor/conn (стійко до переконекту)
from premium_emoji import emoji_to_premium
from commands import seasonal_events as seasonal_mod
from commands.marigolds import _get_marigolds, _add_marigolds, _deduct_marigolds, _ensure_user

router_kupala = Router()

EVENT_ID = "kupala_night"
FOREST_COOLDOWN = timedelta(hours=24)
FERN_DROP_CHANCE = 30  # %

# Фото лісу для «Походу до лісу».
FOREST_PHOTO_PATH = Path(__file__).resolve().parent.parent / "Media" / "Ліс.jpg"

# Предмети інвентарю івенту (крім лимонів, що живуть у users.marigolds).
ITEM_FERN = "fern"
ITEM_WREATH_LUCKY = "wreath_lucky"
ITEM_WREATH_MAGIC = "wreath_magic"

ITEM_LABELS = {
    ITEM_FERN: "🌿 Гілочка папороті",
    ITEM_WREATH_LUCKY: "💮 Вінок «Щаслива ніч»",
    ITEM_WREATH_MAGIC: "🔮 Вінок «Магія Купала»",
}

# Вінок → id бафа, який він дає (ефекти вмикаються в нічному резолві).
WREATH_BUFFS = {
    ITEM_WREATH_LUCKY: "lucky_night",
    ITEM_WREATH_MAGIC: "kupala_magic",
}
BUFF_LABELS = {
    "lucky_night": "💮 Щаслива ніч",
    "kupala_magic": "🔮 Магія Купала",
}

# Рецепти: cost = {item_id або 'marigold': кількість}, result = item_id вінка.
RECIPES = {
    ITEM_WREATH_LUCKY: {
        "name": "💮 Вінок «Щаслива ніч»",
        "cost": {"marigold": 3},
        "desc": "Дає баф «Щаслива ніч» (Аль Капоне б'є наосліп).",
    },
    ITEM_WREATH_MAGIC: {
        "name": "🔮 Вінок «Магія Купала»",
        "cost": {"marigold": 3, ITEM_FERN: 3},
        "desc": "Дає баф «Магія Купала» (50% шанс відбити нічну дію + квітка).",
    },
}


# ── DB helpers ──────────────────────────────────────────────────────────────

def _inv_get_sync(user_id: int, item_id: str) -> int:
    _db.cursor.execute(
        "SELECT COALESCE(quantity, 0) FROM kupala_inventory WHERE user_id = %s AND item_id = %s",
        (user_id, item_id),
    )
    row = _db.cursor.fetchone()
    return int(row[0]) if row else 0


def _inv_add_sync(user_id: int, item_id: str, count: int) -> None:
    _ensure_user(user_id)
    _db.cursor.execute(
        """
        INSERT INTO kupala_inventory (user_id, item_id, quantity)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = kupala_inventory.quantity + EXCLUDED.quantity
        """,
        (user_id, item_id, count),
    )
    _db.conn.commit()


def _inv_deduct_sync(user_id: int, item_id: str, count: int) -> bool:
    if _inv_get_sync(user_id, item_id) < count:
        return False
    _db.cursor.execute(
        "UPDATE kupala_inventory SET quantity = quantity - %s WHERE user_id = %s AND item_id = %s",
        (count, user_id, item_id),
    )
    _db.conn.commit()
    return True


def _forest_trip_at_sync(user_id: int):
    _db.cursor.execute("SELECT forest_trip_at FROM kupala_player WHERE user_id = %s", (user_id,))
    row = _db.cursor.fetchone()
    return row[0] if row else None


def _set_forest_trip_now_sync(user_id: int) -> None:
    _db.cursor.execute(
        """
        INSERT INTO kupala_player (user_id, forest_trip_at)
        VALUES (%s, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id) DO UPDATE SET forest_trip_at = CURRENT_TIMESTAMP
        """,
        (user_id,),
    )
    _db.conn.commit()


async def _inv_get(user_id, item_id):
    return await run_db_call_async(_inv_get_sync, user_id, item_id)


async def _inv_add(user_id, item_id, count):
    return await run_db_call_async(_inv_add_sync, user_id, item_id, count)


async def _inv_deduct(user_id, item_id, count):
    return await run_db_call_async(_inv_deduct_sync, user_id, item_id, count)


def _pending_get_sync(user_id: int):
    _db.cursor.execute("SELECT buff_id FROM kupala_pending_buffs WHERE user_id = %s", (user_id,))
    row = _db.cursor.fetchone()
    return row[0] if row else None


def _pending_set_sync(user_id: int, buff_id: str) -> None:
    _db.cursor.execute(
        """
        INSERT INTO kupala_pending_buffs (user_id, buff_id, applied_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id) DO UPDATE SET buff_id = EXCLUDED.buff_id, applied_at = CURRENT_TIMESTAMP
        """,
        (user_id, buff_id),
    )
    _db.conn.commit()


def _pending_consume_many_sync(user_ids) -> dict:
    """Повертає {user_id: buff_id} для переданих гравців і ОДРАЗУ видаляє ці записи (споживає)."""
    if not user_ids:
        return {}
    ids = tuple(int(u) for u in user_ids)
    _db.cursor.execute(
        "SELECT user_id, buff_id FROM kupala_pending_buffs WHERE user_id IN %s",
        (ids,),
    )
    result = {int(r[0]): r[1] for r in (_db.cursor.fetchall() or [])}
    if result:
        _db.cursor.execute(
            "DELETE FROM kupala_pending_buffs WHERE user_id IN %s",
            (tuple(result.keys()),),
        )
        _db.conn.commit()
    return result


async def _forest_trip_at(user_id):
    return await run_db_call_async(_forest_trip_at_sync, user_id)


async def _pending_get(user_id):
    return await run_db_call_async(_pending_get_sync, user_id)


async def _pending_set(user_id, buff_id):
    return await run_db_call_async(_pending_set_sync, user_id, buff_id)


async def load_and_consume_pending_buffs(user_ids) -> dict:
    """Для старту гри: зчитати й спожити pending-бафи учасників → {user_id: buff_id}."""
    return await run_db_call_async(_pending_consume_many_sync, user_ids)


async def _set_forest_trip_now(user_id):
    return await run_db_call_async(_set_forest_trip_now_sync, user_id)


async def _get_marigolds_async(user_id):
    return await run_db_call_async(_get_marigolds, user_id)


async def _add_marigolds_async(user_id, count):
    return await run_db_call_async(_add_marigolds, user_id, count)


async def _deduct_marigolds_async(user_id, count):
    return await run_db_call_async(_deduct_marigolds, user_id, count)


# ── Gate ────────────────────────────────────────────────────────────────────

async def _event_active() -> bool:
    return (await seasonal_mod.get_active_event_id()) == EVENT_ID


def _fmt_remaining(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 0:
        total = 0
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    if h > 0:
        return f"{h} год {m} хв"
    return f"{m} хв"


# ── UI ──────────────────────────────────────────────────────────────────────

def _hub_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="🌲 Похід до лісу", callback_data="kupala_forest")
    b.button(text="🏵 Крафт вінків", callback_data="kupala_craft")
    b.button(text="🎒 Інвентар", callback_data="kupala_inv")
    b.adjust(1)
    return b.as_markup()


def _back_keyboard(target="kupala_home"):
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data=target)
    return b.as_markup()


def _hub_text() -> str:
    return emoji_to_premium(
        "☀️ <b>Купальська ніч</b> ☀️\n\n"
        "Збирай інгредієнти в лісі та плети вінки з бафами.\n\n"
        "⬇️ Оберіть дію:"
    )


async def _render(callback: CallbackQuery, text: str, keyboard, photo: Path = None):
    """Показати екран, коректно перемикаючись між фото та текстом.
    Якщо потрібне фото — шлемо нове фото-повідомлення й видаляємо старе.
    Якщо текст, а поточне повідомлення — фото — теж пере-надсилаємо.
    Інакше просто редагуємо текст."""
    msg = callback.message
    try:
        if photo and photo.is_file():
            await msg.answer_photo(
                photo=FSInputFile(str(photo)), caption=text,
                reply_markup=keyboard, parse_mode="html",
            )
            try:
                await msg.delete()
            except Exception:
                pass
            return
        if getattr(msg, "photo", None):
            await msg.answer(text, reply_markup=keyboard, parse_mode="html")
            try:
                await msg.delete()
            except Exception:
                pass
            return
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="html")
    except Exception:
        try:
            await msg.answer(text, reply_markup=keyboard, parse_mode="html")
        except Exception:
            pass


@router_kupala.message(Command("kupala"), F.chat.type == ChatType.PRIVATE)
async def cmd_kupala(message: Message):
    if not await _event_active():
        await message.answer(
            emoji_to_premium("☀️ Івент «Купальська ніч» зараз не активний."),
            parse_mode="html",
        )
        return
    if FOREST_PHOTO_PATH.is_file():
        await message.answer_photo(
            photo=FSInputFile(str(FOREST_PHOTO_PATH)),
            caption=_hub_text(), reply_markup=_hub_keyboard(), parse_mode="html",
        )
    else:
        await message.answer(_hub_text(), reply_markup=_hub_keyboard(), parse_mode="html")


@router_kupala.message(Command("kupala"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_kupala_group_reject(message: Message):
    """У групах команда не працює — лише в ПП із ботом."""
    await message.reply("☀️ Команда /kupala доступна лише в особистих повідомленнях з ботом.")


@router_kupala.callback_query(F.data == "kupala_home")
async def kupala_home(callback: CallbackQuery):
    if not await _event_active():
        await callback.answer("Івент не активний.", show_alert=True)
        return
    await _render(callback, _hub_text(), _hub_keyboard(), photo=FOREST_PHOTO_PATH)
    await callback.answer()


@router_kupala.callback_query(F.data == "kupala_forest")
async def kupala_forest(callback: CallbackQuery):
    if not await _event_active():
        await callback.answer("Івент не активний.", show_alert=True)
        return
    uid = callback.from_user.id
    last = await _forest_trip_at(uid)
    if isinstance(last, datetime):
        # БД повертає naive timestamp (CURRENT_TIMESTAMP, UTC) — порівнюємо з utcnow().
        remaining = FOREST_COOLDOWN - (datetime.utcnow() - last)
        if remaining.total_seconds() > 0:
            await callback.answer(
                f"🌲 Ти вже ходив до лісу. Спробуй ще через {_fmt_remaining(remaining)}.",
                show_alert=True,
            )
            return

    await _set_forest_trip_now(uid)
    marigolds_got = random.randint(1, 2)
    await _add_marigolds_async(uid, marigolds_got)
    fern_got = 1 if random.randint(1, 100) <= FERN_DROP_CHANCE else 0
    if fern_got:
        await _inv_add(uid, ITEM_FERN, fern_got)

    lines = [
        "🌲 <b>Похід до лісу</b>\n",
        f"🏵 Лимони: <b>+{marigolds_got}</b>",
    ]
    if fern_got:
        lines.append(f"🌿 Гілочка папороті: <b>+{fern_got}</b>")
    else:
        lines.append("🌿 Папороть цього разу не знайшлася (шанс 30%).")
    lines.append("\nПриходь знову за 24 години.")
    text = emoji_to_premium("\n".join(lines))
    # Показуємо фото лісу з результатом у підписі.
    await _render(callback, text, _back_keyboard(), photo=FOREST_PHOTO_PATH)
    await callback.answer()


@router_kupala.callback_query(F.data == "kupala_craft")
async def kupala_craft_menu(callback: CallbackQuery):
    if not await _event_active():
        await callback.answer("Івент не активний.", show_alert=True)
        return
    uid = callback.from_user.id
    marigolds = await _get_marigolds_async(uid)
    fern = await _inv_get(uid, ITEM_FERN)

    b = InlineKeyboardBuilder()
    for item_id, rec in RECIPES.items():
        cost = rec["cost"]
        affordable = marigolds >= cost.get("marigold", 0) and fern >= cost.get(ITEM_FERN, 0)
        mark = "✅" if affordable else "🔒"
        b.button(text=f"{mark} {rec['name']}", callback_data=f"kupala_craft_do:{item_id}")
    b.button(text="⬅️ Назад", callback_data="kupala_home")
    b.adjust(1)

    lines = ["🏵 <b>Крафт вінків</b>\n", f"У тебе: 🏵 {marigolds} · 🌿 {fern}\n"]
    for item_id, rec in RECIPES.items():
        cost = rec["cost"]
        cost_str = ", ".join(
            f"{n}×{'🏵' if k == 'marigold' else '🌿'}"
            for k, n in cost.items()
        )
        lines.append(f"• <b>{rec['name']}</b> — {cost_str}\n  <i>{rec['desc']}</i>")
    text = emoji_to_premium("\n".join(lines))
    await _render(callback, text, b.as_markup())
    await callback.answer()


@router_kupala.callback_query(F.data.startswith("kupala_craft_do:"))
async def kupala_craft_do(callback: CallbackQuery):
    if not await _event_active():
        await callback.answer("Івент не активний.", show_alert=True)
        return
    uid = callback.from_user.id
    item_id = (callback.data or "").split(":", 1)[1]
    rec = RECIPES.get(item_id)
    if not rec:
        await callback.answer("Невідомий рецепт.", show_alert=True)
        return
    cost = rec["cost"]
    need_marigolds = cost.get("marigold", 0)
    need_fern = cost.get(ITEM_FERN, 0)

    marigolds = await _get_marigolds_async(uid)
    fern = await _inv_get(uid, ITEM_FERN)
    if marigolds < need_marigolds or fern < need_fern:
        await callback.answer("Недостатньо інгредієнтів.", show_alert=True)
        return

    # Списуємо: спершу лимони, потім папороть; з відкатом при невдачі.
    if need_marigolds and not await _deduct_marigolds_async(uid, need_marigolds):
        await callback.answer("Недостатньо лимонів.", show_alert=True)
        return
    if need_fern and not await _inv_deduct(uid, ITEM_FERN, need_fern):
        if need_marigolds:
            await _add_marigolds_async(uid, need_marigolds)  # повертаємо
        await callback.answer("Недостатньо папороті.", show_alert=True)
        return

    # Вінок видаємо як ЗВИЧАЙНИЙ баф (item_id == buff_id у каталозі ITEMS):
    # він з'явиться в інвентарі бафів у профілі й активується як усі бафи.
    from commands.buff_shop import admin_grant_buff_to_user
    ok, _msg = await run_db_call_async(admin_grant_buff_to_user, uid, item_id)
    if not ok:
        # Повертаємо інгредієнти при невдачі видачі.
        if need_marigolds:
            await _add_marigolds_async(uid, need_marigolds)
        if need_fern:
            await _inv_add(uid, ITEM_FERN, need_fern)
        await callback.answer("Не вдалося створити вінок. Спробуй ще раз.", show_alert=True)
        return
    await callback.answer(f"Створено: {rec['name']} → у твоєму інвентарі бафів (профіль).")
    # Перемальовуємо меню крафту з оновленими залишками.
    await kupala_craft_menu(callback)


@router_kupala.callback_query(F.data == "kupala_inv")
async def kupala_inventory(callback: CallbackQuery):
    if not await _event_active():
        await callback.answer("Івент не активний.", show_alert=True)
        return
    uid = callback.from_user.id
    marigolds = await _get_marigolds_async(uid)
    fern = await _inv_get(uid, ITEM_FERN)

    text = emoji_to_premium(
        "🎒 <b>Інвентар «Купальська ніч»</b>\n\n"
        f"🏵 Лимони: <b>{marigolds}</b>\n"
        f"🌿 Гілочка папороті: <b>{fern}</b>\n\n"
        "<i>Скрафтлені вінки — у твоєму інвентарі бафів (профіль 👤). "
        "Активуються як звичайні бафи.</i>"
    )
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data="kupala_home")
    b.adjust(1)
    await _render(callback, text, b.as_markup())
    await callback.answer()
