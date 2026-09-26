# Контрабанда: один раз на 3 год, події 72 год, перехоплення, охорона.
import json
import random
import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.database import (
    cursor,
    conn,
    get_balance,
    add_balance_to_user,
    deduct_balance,
    add_gold_to_user,
    contraband_can_use,
    contraband_set_used,
    contraband_should_trigger_event,
    contraband_set_event,
    contraband_create_interception,
    contraband_get_interception,
    contraband_resolve_interception,
    contraband_interception_still_valid,
)
from commands.start import add_user_to_db
from premium_emoji import emoji_to_premium

# Засновники бота - без кулдауну на контрабанду
BOT_OWNER_IDS = [1859870653]

# Кулдаун між запусками /contraband (години)
CONTRABAND_COOLDOWN_HOURS = 3

router_contraband = Router()


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0

# Типи вантажу: (базовий прибуток 💵, шанс поліції %, шанс рідкісний %, шанс велика удача %)
CARGO = {
    "alcohol": ("🍷 Алкоголь", 15, 10, 15, 10),
    "weapon": ("🔫 Зброя", 22, 20, 12, 8),
    "rare": ("💎 Рідкісний товар", 28, 25, 18, 12),
}

# Маршрути: (назва, множник прибутку, зміна ризику поліції в п.п.)
ROUTES = {
    "lviv": ("🇮🇹 Палермо", 1.0, 0),
    "peremyshl": ("🇮🇹 Неаполь", 1.3, 10),
    "krakow": ("🇮🇹 Катанія", 1.15, 5),
    "prague": ("🇮🇹 Мессіна", 0.9, -10),
}

# Події: раз на 72 год при /contraband
EVENT_POLICE_RAID = "police_raid"   # +10% провал (15% -> 25%)
EVENT_SMUGGLER_NIGHT = "smuggler_night"  # +15% успіх (60% -> 75%)

INTERCEPTION_CHANCE = 0.30
INTERCEPTION_SUCCESS = 0.40
INTERCEPTION_SHOOTOUT = 0.40
INTERCEPTION_SMUGGLER_WINS = 0.20
GUARD_PRICE = 200
GUARD_INTERCEPT_BONUS = 0.20   # +20% відбити перехоплення
GUARD_SHOOTOUT_REDUCE = 0.10   # -10% втратити товар у перестрілці
INTERCEPTION_MAX_AGE = 300


def _get_random_user_ids_for_rumor(exclude_user_id: int, limit: int = 15):
    """Повертає список випадкових user_id з БД (хто колись писав боту), крім exclude_user_id."""
    rows = _db_fetchall(
        "SELECT id FROM users WHERE id != %s ORDER BY RANDOM() LIMIT %s",
        (exclude_user_id, limit),
    )
    return [row[0] for row in (rows or [])]


def _get_active_interception_by_id(interception_id: int):
    return _db_fetchone(
        "SELECT id, smuggler_id, cargo_type, route, has_guard FROM contraband_interception WHERE id = %s AND resolved = FALSE",
        (interception_id,),
    )


def _grant_random_cheap_buff(user_id: int) -> str:
    """Видає випадковий дешевий баф. Повертає назву бафа або порожній рядок."""
    from commands.buff_shop import ITEMS, ItemCategory
    cheap_ids = [k for k, v in ITEMS.items() if v.category == ItemCategory.CHEAP]
    if not cheap_ids:
        return ""
    buff_id = random.choice(cheap_ids)
    item = ITEMS[buff_id]
    metadata = {
        "category": item.category.value,
        "item_type": item.item_type.value,
        "activation_time": item.activation_time.value,
        "cooldown": item.cooldown.value,
        "priority": item.priority,
    }
    if getattr(item, "effect_data", None):
        metadata["effect_data"] = item.effect_data
    try:
        _db_execute(
            """
            INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity)
            VALUES (%s, %s, %s, FALSE, %s::jsonb, 1)
            ON CONFLICT (user_id, buff_id) DO UPDATE
              SET quantity = user_buffs.quantity + 1
            """,
            (user_id, buff_id, item.name, json.dumps(metadata)),
        )
        conn.commit()
        return f"{item.emoji} {item.name}"
    except Exception:
        conn.rollback()
        return ""


@router_contraband.message(Command("contraband"), F.chat.type == "private")
async def cmd_contraband(message: Message, bot: Bot):
    await add_user_to_db(message)
    user_id = message.from_user.id

    # Засновники бота не обмежені кулдауном
    if user_id not in BOT_OWNER_IDS and not contraband_can_use(user_id, CONTRABAND_COOLDOWN_HOURS):
        row = _db_fetchone("SELECT last_used_at FROM contraband_cooldown WHERE user_id = %s", (user_id,))
        if row:
            last = row[0]
            if hasattr(last, "replace"):
                last = last.replace(tzinfo=None)
            next_use = last + timedelta(hours=CONTRABAND_COOLDOWN_HOURS)
            left = next_use - datetime.now()
            hours = max(0, int(left.total_seconds() // 3600))
            mins = max(0, int((left.total_seconds() % 3600) // 60))
            await message.answer(
                f"⏱️ Контрабанду можна запустити раз на {CONTRABAND_COOLDOWN_HOURS} години.\n"
                f"Наступна спроба через: {hours} год {mins} хв."
            )
            return

    # Можлива подія раз на 72 год
    event_type = None
    if contraband_should_trigger_event(user_id, 72):
        r = random.random()
        if r < 0.15:
            event_type = EVENT_POLICE_RAID
            contraband_set_event(user_id, event_type)
        elif r < 0.30:
            event_type = EVENT_SMUGGLER_NIGHT
            contraband_set_event(user_id, event_type)

    intro = (
        "📦 <b>Контрабанда</b>\n\n"
        "Через кордон можна провести товар.\n"
        "Але пам'ятай - поліція не спить.\n\n"
        "📦 <b>Види контрабанди</b>\n"
        "🍷 Алкоголь - безпечніше, менший прибуток\n"
        "🔫 Зброя - більше прибутку, більший шанс поліції\n"
        "💎 Рідкісний товар - великий ризик, золото/бафи\n\n"
        "Що перевозимо?"
    )
    if event_type == EVENT_POLICE_RAID:
        intro += "\n\n🚓 <b>Облава поліції</b>\nСьогодні шанс провалу контрабанди +10%"
    elif event_type == EVENT_SMUGGLER_NIGHT:
        intro += "\n\n🌫 <b>Ніч контрабандистів</b>\nУспіх +15%"

    builder = InlineKeyboardBuilder()
    builder.button(text="🍷 Алкоголь", callback_data="cb_cargo:alcohol")
    builder.button(text="🔫 Зброя", callback_data="cb_cargo:weapon")
    builder.button(text="💎 Рідкісний товар", callback_data="cb_cargo:rare")
    builder.adjust(1)

    await message.answer(emoji_to_premium(intro), reply_markup=builder.as_markup(), parse_mode="html")


@router_contraband.callback_query(F.data.startswith("cb_intercept:"))
async def cb_intercept(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    try:
        iid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Помилка.", show_alert=True)
        return
    row = _get_active_interception_by_id(iid)
    if not row:
        await callback.answer("Перехоплення вже розігралось.", show_alert=True)
        return
    if row[1] == user_id:
        await callback.answer("Не можна перехопити власний вантаж.", show_alert=True)
        return
    if not contraband_resolve_interception(iid, user_id):
        await callback.answer("Хтось вже натиснув.", show_alert=True)
        return

    smuggler_id, cargo_type, route, has_guard = row[1], row[2], row[3], row[4]
    roll = random.random()
    # з охороною: +20% відбити, -10% втратити в перестрілці
    if has_guard:
        intercept_success = INTERCEPTION_SUCCESS - GUARD_INTERCEPT_BONUS  # 20%
        shootout = INTERCEPTION_SHOOTOUT - GUARD_SHOOTOUT_REDUCE  # 30%
        smuggler_wins = INTERCEPTION_SMUGGLER_WINS + GUARD_INTERCEPT_BONUS + GUARD_SHOOTOUT_REDUCE  # 50%
    else:
        intercept_success = INTERCEPTION_SUCCESS
        shootout = INTERCEPTION_SHOOTOUT
        smuggler_wins = INTERCEPTION_SMUGGLER_WINS

    if roll < intercept_success:
        add_balance_to_user(user_id, 20)
        await callback.message.edit_text(
            "📦 <b>Ви перехопили чужий вантаж.</b>\nВи отримали 20💵",
            parse_mode="html",
        )
        try:
            await bot.send_message(smuggler_id, emoji_to_premium("🚬 Хтось перехопив ваш товар."), parse_mode="html")
        except Exception:
            pass
    elif roll < intercept_success + shootout:
        await callback.message.edit_text(
            emoji_to_premium("🔫 На дорозі пролунали постріли. Товар втрачено.\n"),
            parse_mode="html",
        )
        try:
            await bot.send_message(smuggler_id, emoji_to_premium("🔫 Перестрілка - товар втрачено."), parse_mode="html")
        except Exception:
            pass
    else:
        await callback.message.edit_text(
            emoji_to_premium("🔪 Контрабандист помітив засідку. Ви втекли ні з чим.\nКонтрабанда продовжується у нього."),
            parse_mode="html",
        )
        ev_row = _db_fetchone("SELECT event_type FROM contraband_events WHERE user_id = %s", (smuggler_id,))
        smuggle_event = (ev_row[0] if ev_row and ev_row[0] else None)
        asyncio.create_task(_run_contraband_roll(bot, smuggler_id, cargo_type, route, has_guard, event_type=smuggle_event))
    await callback.answer()


async def _run_contraband_roll(
    bot: Bot,
    user_id: int,
    cargo_type: str,
    route: str,
    has_guard: bool,
    event_type: str = None,
    message_to_edit=None,
):
    """
    Виконує один рол контрабанди.
    Якщо message_to_edit задано - результат показується в тому ж повідомленні (редагування).
    Інакше - надсилається нове повідомлення в чат user_id (наприклад, після перехоплення).
    """
    label, base_money, base_police, base_rare, base_luck = CARGO.get(cargo_type, ("?", 15, 15, 15, 10))
    route_label, profit_mult, police_delta = ROUTES.get(route, ("?", 1.0, 0))
    profit_mult = profit_mult or 1.0
    police_delta = police_delta or 0

    if event_type == EVENT_POLICE_RAID:
        base_police += 10
    elif event_type == EVENT_SMUGGLER_NIGHT:
        base_police -= 15
    success = 60
    rare = 15
    big_luck = 10
    police = 15
    if event_type == EVENT_POLICE_RAID:
        police = 25
        success = 50
    elif event_type == EVENT_SMUGGLER_NIGHT:
        success = 75
        police = 10
        rare = 10
        big_luck = 5

    roll = random.randint(1, 100)
    result_text = ""
    if roll <= success:
        amount = int(base_money * profit_mult)
        add_balance_to_user(user_id, amount)
        result_text = f"📦 Контрабанда пройшла через кордон.\nВи отримали {amount}💵"
    elif roll <= success + rare:
        buff_name = _grant_random_cheap_buff(user_id)
        result_text = f"🧳 У ящику виявився особливий товар.\nВи отримали випадковий баф: {buff_name or 'баф'}."
    elif roll <= success + rare + big_luck:
        add_gold_to_user(user_id, 2)
        result_text = "💎 Через кордон пройшов дуже цінний товар.\nВи отримали 2🪙"
    else:
        loss = int(base_money * profit_mult * 1.25)
        balance_now = get_balance(user_id)
        actual_loss = min(loss, balance_now) if balance_now > 0 else 0
        if actual_loss > 0:
            deduct_balance(user_id, actual_loss)
        result_text = f"🚓 Вас зупинив патруль. Товар конфісковано.\nВи втратили {actual_loss}💵"

    result_text = emoji_to_premium(result_text)
    if message_to_edit:
        try:
            await message_to_edit.edit_text(result_text, parse_mode="html")
        except Exception:
            pass
    else:
        try:
            await bot.send_message(user_id, result_text, parse_mode="html")
        except Exception:
            pass


@router_contraband.callback_query(F.data.startswith("cb_cargo:"))
async def cb_cargo(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    cargo_type = (callback.data or "").split(":", 1)[1]
    if cargo_type not in CARGO:
        await callback.answer("Невірний вибір.", show_alert=True)
        return

    balance = get_balance(user_id)
    event_type = None
    row = _db_fetchone("SELECT event_type FROM contraband_events WHERE user_id = %s", (user_id,))
    if row and row[0]:
        event_type = row[0]

    text = (
        "🗺 <b>Обери маршрут</b>\n\n"
        "🇮🇹 Палермо - стандартний прибуток і ризик\n"
        "🇮🇹 Неаполь - прибуток +30%, ризик поліції +10%\n"
        "🇮🇹 Катанія - прибуток +15%, ризик +5%\n"
        "🇮🇹 Мессіна - прибуток -10%, ризик -10%\n\n"
        "Можна найняти охорону: +20% відбити перехоплення, -10% втратити товар у перестрілці."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🇮🇹 Палермо", callback_data=f"cb_route:{cargo_type}:lviv")
    builder.button(text="🇮🇹 Неаполь", callback_data=f"cb_route:{cargo_type}:peremyshl")
    builder.button(text="🇮🇹 Катанія", callback_data=f"cb_route:{cargo_type}:krakow")
    builder.button(text="🇮🇹 Мессіна", callback_data=f"cb_route:{cargo_type}:prague")
    builder.adjust(2)
    if balance >= GUARD_PRICE:
        builder.row(
            InlineKeyboardButton(text=f"🛡 Найняти охорону - {GUARD_PRICE}💵", callback_data=f"cb_guard:{cargo_type}")
        )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
    await callback.answer()


@router_contraband.callback_query(F.data.startswith("cb_guard:"))
async def cb_guard(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    cargo_type = (callback.data or "").split(":", 1)[1]
    if get_balance(user_id) < GUARD_PRICE:
        await callback.answer("Недостатньо грошей.", show_alert=True)
        return
    deduct_balance(user_id, GUARD_PRICE)
    text = (
        "🗺 <b>Обери маршрут</b> (охорона найнята)\n\n"
        "🇮🇹 Палермо | 🇮🇹 Неаполь | 🇮🇹 Катанія | 🇮🇹 Мессіна"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🇮🇹 Палермо", callback_data=f"cb_go:{cargo_type}:lviv:1")
    builder.button(text="🇮🇹 Неаполь", callback_data=f"cb_go:{cargo_type}:peremyshl:1")
    builder.button(text="🇮🇹 Катанія", callback_data=f"cb_go:{cargo_type}:krakow:1")
    builder.button(text="🇮🇹 Мессіна", callback_data=f"cb_go:{cargo_type}:prague:1")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
    await callback.answer("Охорону найнято.")


@router_contraband.callback_query(F.data.startswith("cb_route:"))
async def cb_route(callback: CallbackQuery, bot: Bot):
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer("Помилка.", show_alert=True)
        return
    cargo_type, route = parts[1], parts[2]
    if cargo_type not in CARGO or route not in ROUTES:
        await callback.answer("Невірний вибір.", show_alert=True)
        return
    await _do_contraband_run(callback, bot, callback.from_user.id, cargo_type, route, has_guard=False)


@router_contraband.callback_query(F.data.startswith("cb_go:"))
async def cb_go(callback: CallbackQuery, bot: Bot):
    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer("Помилка.", show_alert=True)
        return
    cargo_type, route, guard = parts[1], parts[2], parts[3] == "1"
    if cargo_type not in CARGO or route not in ROUTES:
        await callback.answer("Невірний вибір.", show_alert=True)
        return
    await _do_contraband_run(callback, bot, callback.from_user.id, cargo_type, route, has_guard=guard)


async def _do_contraband_run(callback: CallbackQuery, bot: Bot, user_id: int, cargo_type: str, route: str, has_guard: bool):
    if user_id not in BOT_OWNER_IDS and not contraband_can_use(user_id, CONTRABAND_COOLDOWN_HOURS):
        await callback.answer("Кулдаун ще не закінчився.", show_alert=True)
        return
    if user_id not in BOT_OWNER_IDS:
        contraband_set_used(user_id)

    event_type = None
    row = _db_fetchone("SELECT event_type FROM contraband_events WHERE user_id = %s", (user_id,))
    if row and row[0]:
        event_type = row[0]

    # 30% створити перехоплення - випадковим людям в ЛС приходить «Чутки міста» (пробуємо дописати поки хтось не отримає)
    interception_id = None
    if random.random() < INTERCEPTION_CHANCE:
        interception_id = contraband_create_interception(user_id, cargo_type, route, has_guard)
        rumor_text = emoji_to_premium(
            "🌫 <b>Чутки міста</b>\n\n"
            "Кажуть, цієї ночі через кордон іде підозрілий вантаж.\n"
            "Хтось може спробувати його перехопити."
        )
        rumor_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🕵️ Перехопити вантаж", callback_data=f"cb_intercept:{interception_id}")]
        ])
        sent = False
        for rumor_target_id in _get_random_user_ids_for_rumor(user_id):
            if not interception_id:
                break
            try:
                await bot.send_message(
                    rumor_target_id,
                    rumor_text,
                    reply_markup=rumor_kb,
                    parse_mode="html",
                )
                sent = True
                break
            except Exception:
                continue
        if not sent:
            pass  # нікого не знайшли або всі заблокували бота - контрабанда все одно чекає 5 хв
        await callback.message.edit_text(
            emoji_to_premium(
                "🌫 <b>Чутки пішли містом.</b> Хтось може спробувати перехопити ваш вантаж. "
                "Чекайте до 5 хвилин - якщо ніхто не перехопить, контрабанда піде далі."
            ),
            parse_mode="html",
        )
        await callback.answer()
        # Даємо 5 хвилин на перехоплення; якщо ніхто не натисне - рол як завжди
        await asyncio.sleep(INTERCEPTION_MAX_AGE)
        rec = contraband_get_interception(interception_id) if interception_id else None
        if rec and not rec[4]:  # not resolved
            _db_execute("UPDATE contraband_interception SET resolved = TRUE WHERE id = %s", (interception_id,))
            conn.commit()
            await _run_contraband_roll(
                bot, user_id, cargo_type, route, has_guard, event_type,
                message_to_edit=callback.message,
            )
        return

    await callback.message.edit_text("🎲 Йде перевірка на кордоні...", parse_mode="html")
    await callback.answer()
    await asyncio.sleep(2)
    await _run_contraband_roll(
        bot, user_id, cargo_type, route, has_guard, event_type,
        message_to_edit=callback.message,
    )
