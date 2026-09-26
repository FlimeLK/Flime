"""
Весняний адвент-календар: 31 день (дні 1–31).
Працює лише у вказаний період (наприклад 1–31 березня). День N відкривається N-го числа цього періоду.
Пропущений день відкрити вже не можна. Команда /advent.
"""

from datetime import datetime, timedelta
import json
import os
import random

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.database import cursor, conn, grant_clown_card_to_user
from commands.start import BOT_OWNER_ID
from premium_emoji import emoji_to_premium

# Шлях до відео Клоун (унікальна карточка при випаданні з адвенту)
_ADVENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MEDIA_DIR = os.path.join(_ADVENT_DIR, "Media")
ROLE_MEDIA_DIR = os.path.join(MEDIA_DIR, "role_announce")
CLOWN_VIDEO_PATH = os.path.join(ROLE_MEDIA_DIR, "Клоун(Унікальне).mp4")
CLOWN_VIDEO_ALT = os.path.join(MEDIA_DIR, "Клоун(Унікальне).mp4")

# Декілька власників бота, які мають повний доступ до службових команд адвенту
BOT_OWNER_IDS = [BOT_OWNER_ID]

# Повний текст сюжету при випаданні картки Клоун (дублює текст з story_cards для відправки)
CLOWN_STORY_FULL = (
    "💥ВИ ВІДКРИЛИ ЧАСТИНУ СЮЖЕТУ💥\n\n"
    "🤡 Я – Клоун, Той, Хто Міняє Маски на Сцені Хаосу 🤡\n\n"
    "Сідай на арену старого цирку на околиці Львова, де шапіто давно проржавіло, а клітка лева стоїть порожня, ніби чекає на чергову жертву. "
    "Я в кольоровому костюмі, з червоним носом, що блищить під єдиним прожектором, в руках - рожевий молоток і маска з посмішкою диявола. "
    "Музика грамофона грає \"Вальс чаклунів\" задом наперед. "
    "Ти - мій єдиний глядач цієї ночі. Слухай сміх, бо він ховає крик.\n\n"
    "Я не народився клоуном. Я став ним. "
    "1898-й, Варшава, родина циркових акробатів - батько жонглер, мати - канатохідка. "
    "Ми приїхали до Львова 1920-го, ставили шапіто на Ринку, смішили бідних хлібом й жартами. "
    "Люди сміялися, кидали копійки, забували про голод.\n\n"
    "Пацифікація 1930-го все зламала. "
    "Польські жандарми спалили цирк - \"повстанці ховаються під шатром\". "
    "Батько намагався пожартувати з офіцером - отримав кулю в живіт. Мати впала з каната в полум'я.\n\n"
    "Мені було 32. Я вижив, бо сміявся: \"Господарі, це ж частина шоу!\". Вони засміялися й відпустили.\n\n"
    "З того дня я - Клоун. Не для сміху. Для плутанини. "
    "Ходжу по кав'ярнях Великого Ела, жонглюю сигарами в казино, малюю посмішки на стінах Підзамче. "
    "Аль Капоне думає, що я його блазень - годує варениками, кидає монети. "
    "Комісар Каттані дивиться крізь мене, як крізь повітря. "
    "Але в мене є один трюк - один шанс за всю гру. "
    "Я заходжу до двох гравців, хапаю їхні маски й міняю місцями. "
    "Мафіозі стає Лікарем, Комісар - Маніяком, Мирний - Аль Капоне.\n\n"
    "Хаос! Плани руйнуються, Сім'я гризе лікті, закон сліпий. Це не помста. Це шоу. Найкраще шоу Сицилії.\n\n"
    "Я сміюся не тому, що щасливий. Я сміюся, бо світ - цирк, а я - єдиний, хто знає, де підміна.\n\n"
    "Твоя роль у грі - мій великий трюк. "
    "Ціль: Засіяти хаос і плутанину. За всю гру у тебе один шанс: зайти до двох гравців і поміняти їхні ролі місцями. Це зламає плани будь-якої команди.\n\n"
    "Сміх - найкраща помста. Міняй маски, і шоу почнеться!\n\n"
    "Твоя черга. Кого обміняємо на цій арені? 🤡"
)

# Імпорт для нагород: бафи з каталогу, підписка
try:
    from commands.buff_shop import ITEMS as BUFF_ITEMS
except Exception:
    BUFF_ITEMS = {}


router_advent = Router()


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0

EVENT_KEY = "spring_2025"
FIRST_DAY = 1   # перший день календаря
LAST_DAY = 31   # останній день (31 день: 1, 2, ..., 31)
TOTAL_DAYS = 31
DAYS_LIST = list(range(FIRST_DAY, LAST_DAY + 1))  # [1, 2, ..., 31]

# Конкретні дати проведення адвенту: лише в цей період можна відкривати дні (місяць, день)
ADVENT_START_MONTH = 3   # березень
ADVENT_START_DAY = 1     # 1 березня
ADVENT_END_MONTH = 3     # березень
ADVENT_END_DAY = 31      # 31 березня
ADVENT_DATE_DESC = "з 1 по 31 березня"  # для текстів у боті

# Короткі атмосферні тексти для кожного дня (весна + стиль бота, 1–31)
DAY_TEXTS = {
    1: "Перша тінь весни над містом. Щось прокинулось.",
    2: "Травень пробивається крізь бруківку. Ти це відчуваєш.",
    3: "Вітер змінює напрямок. Сім'я теж готується.",
    4: "Дощ змиває сліди. Ніч стає коротшою.",
    5: "Квітень у повітрі. Хтось уже відкрив вікно.",
    6: "Старий календар показує новий місяць. Пора.",
    7: "Сонце крадеться раніше. Місто просинається.",
    8: "Восьмий день - восьма тінь. Ти йдеш далі.",
    9: "Перші квіти там, де ніхто не чекав. Як завжди.",
    10: "Десятий крок. Весна не питає дозволу.",
    11: "Одинадцять вікон світяться інакше. Щось змінилось.",
    12: "Північ відступає. День тримає оборону.",
    13: "Тринадцять кроків до світанку. Ти вже рахуєш.",
    14: "Два тижні весни. Місто вже не те саме.",
    15: "П'ятнадцять - пів шляху. Пекло чекає, але не сьогодні.",
    16: "Шістнадцятий день. Тіні коротші. Сміливість вища.",
    17: "Вітер з моря. Хтось приїхав. Хтось пішов.",
    18: "Вісімнадцять відкритих дверей. Одна - твоя.",
    19: "Дев'ятнадцять днів. Сім'я пам'ятає кожен.",
    20: "Двадцять - число тиші перед бурею. Або після.",
    21: "Двадцять один. Весна вже не питає - вона диктує.",
    22: "Двадцять два вікна. В одному - світло для тебе.",
    23: "Двадцять три. Місто затамувало подих - ще не кінець.",
    24: "Двадцять чотири години. Ніч коротша. День довший.",
    25: "Двадцять п'ять. Ти вже пройшов більше ніж пів шляху.",
    26: "Двадцять шість днів весни. Залишилось кілька кроків.",
    27: "Двадцять сім. Вітер несе зміни. Ти їх відчуваєш.",
    28: "Двадцять вісім - число нових початків. Один уже твій.",
    29: "Двадцять дев'ять. Останні тіні перед фіналом.",
    30: "Тридцятий день. Завтра - останній. Сім'я чекає.",
    31: "Останній день весняного адвенту. Ти пройшов усі тридцять один. Сім'я не забуде.",
}

# Нагороди за кожен день. Типи: coins (ліри), gold (золоті), buffs (список {buff_id, quantity}), game_vip_days (дні ігрового VIP).
ADVENT_REWARDS: dict[int, dict] = {
    1: {"coins": 50},
    2: {"coins": 30},
    3: {"gold": 1},
    4: {"coins": 80},
    5: {"coins": 50},
    6: {"coins": 100},
    7: {"gold": 2},
    8: {"coins": 120},
    9: {"buff_choice": 1},  # вибір будь-якого робочого (звичайного) бафа
    10: {"coins": 150},
    11: {"gold": 1},
    12: {"coins": 200},
    13: {"buff_choice": 1},  # як у 9-й день - вибір бафа
    14: {"gold": 2},
    15: {"coins": 250},
    16: {"gold": 3},
    17: {"coins": 300},
    18: {"buff_choice": 1},  # людина сама обирає один баф зі списку
    19: {"coins": 350},
    20: {"gold": 4},
    21: {"coins": 400},
    22: {"gold": 5},
    23: {"coins": 450},
    24: {"game_vip_days": 3},
    25: {"coins": 500},
    26: {"gold": 6},
    27: {"coins": 550},
    28: {"gold": 7},
    29: {"buff_choice": 1},  # як у 9-й день - вибір бафа
    30: {"gold": 8},
    31: {"coins": 1000, "gold": 10, "game_vip_days": 7},
}


def is_advent_active() -> bool:
    """Чи зараз триває період адвенту (конкретні дати)."""
    now = datetime.now()
    m, d = now.month, now.day
    return (ADVENT_START_MONTH, ADVENT_START_DAY) <= (m, d) <= (ADVENT_END_MONTH, ADVENT_END_DAY)


def _resolve_clown_video_path() -> str | None:
    """Повертає шлях до відео Клоун (Media або корінь проєкту), або None якщо файлу немає."""
    if os.path.isfile(CLOWN_VIDEO_PATH):
        return CLOWN_VIDEO_PATH
    if os.path.isfile(CLOWN_VIDEO_ALT):
        return CLOWN_VIDEO_ALT
    return None


async def _send_clown_story_to_user(bot: Bot, user_id: int) -> None:
    """Відправляє користувачу відео та повний сюжет картки Клоун (коли вона випала з адвенту)."""
    path = _resolve_clown_video_path()
    if path:
        try:
            await bot.send_video(chat_id=user_id, video=FSInputFile(path))
        except Exception:
            pass
    try:
        await bot.send_message(chat_id=user_id, text=CLOWN_STORY_FULL)
    except Exception:
        pass


def get_today_day() -> int | None:
    """Номер дня календаря (1–31), який сьогодні можна відкрити - лише якщо зараз період адвенту. Інакше None."""
    if not is_advent_active():
        return None
    return datetime.now().day


def get_opened_days(user_id: int) -> set:
    """Повертає множину номерів днів (1–31), які користувач вже відкрив."""
    rows = _db_fetchall(
        "SELECT day_number FROM advent_opens WHERE user_id = %s AND event_key = %s",
        (user_id, EVENT_KEY),
    )
    return {r[0] for r in rows} if rows else set()


def get_unlocked_days(user_id: int) -> set[int]:
    """Дні, які адмін дозволив відкрити поза правилом 'лише сьогодні'."""
    rows = _db_fetchall(
        "SELECT day_number FROM advent_unlocks WHERE user_id = %s AND event_key = %s AND used_at IS NULL",
        (user_id, EVENT_KEY),
    )
    return {int(r[0]) for r in rows} if rows else set()


def grant_unlock_day(user_id: int, day_number: int, granted_by: int) -> bool:
    """Видати користувачу доступ до конкретного дня. True якщо створено/оновлено."""
    try:
        _db_execute(
            """
            INSERT INTO advent_unlocks (user_id, event_key, day_number, granted_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, event_key, day_number)
            DO UPDATE SET granted_by = EXCLUDED.granted_by, granted_at = CURRENT_TIMESTAMP, used_at = NULL
            """,
            (user_id, EVENT_KEY, day_number, granted_by),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


def consume_unlock_day(user_id: int, day_number: int) -> None:
    """Позначити адмін-доступ як використаний (щоб не можна було відкривати нескінченно)."""
    try:
        _db_execute(
            "UPDATE advent_unlocks SET used_at = CURRENT_TIMESTAMP WHERE user_id = %s AND event_key = %s AND day_number = %s AND used_at IS NULL",
            (user_id, EVENT_KEY, day_number),
        )
        conn.commit()
    except Exception:
        conn.rollback()


def can_open_today(user_id: int) -> int | None:
    """День, який сьогодні можна відкрити (лише в період адвенту), або None."""
    today = get_today_day()
    if today is None or today > LAST_DAY:
        return None
    opened = get_opened_days(user_id)
    return today if today not in opened else None


def open_day(user_id: int, day_number: int) -> bool:
    """Відкриває день для користувача. Повертає True при успіху."""
    try:
        affected = _db_execute(
            "INSERT INTO advent_opens (user_id, event_key, day_number) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (user_id, EVENT_KEY, day_number),
        )
        conn.commit()
        return affected > 0
    except Exception:
        conn.rollback()
        return False


def apply_advent_rewards(user_id: int, day_number: int) -> list[str]:
    """
    Нараховує нагороди за день адвенту (ADVENT_REWARDS). Повертає список рядків для повідомлення (наприклад "💰 100 лір").
    """
    rewards = ADVENT_REWARDS.get(day_number) or {}
    lines = []
    try:
        _db_execute("INSERT INTO users (id, balance, donate_coins) VALUES (%s, 0, 0) ON CONFLICT (id) DO NOTHING", (user_id,))
        conn.commit()
    except Exception:
        conn.rollback()

    coins = rewards.get("coins") or 0
    if coins > 0:
        _db_execute("UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s", (coins, user_id))
        lines.append(f"💰 {coins} лір")

    gold = rewards.get("gold") or 0
    if gold > 0:
        _db_execute("UPDATE users SET donate_coins = COALESCE(donate_coins, 0) + %s WHERE id = %s", (gold, user_id))
        lines.append(f"🪙 {gold} золотих монет")

    # buff_choice - нагорода "вибери баф сам", не нараховується тут
    if rewards.get("buff_choice"):
        return lines

    buffs = rewards.get("buffs") or []
    for entry in buffs:
        buff_id = entry.get("buff_id")
        qty = max(1, int(entry.get("quantity", 1)))
        item = BUFF_ITEMS.get(buff_id) if buff_id else None
        if not item:
            continue
        metadata = {
            "category": item.category.value,
            "item_type": item.item_type.value,
            "activation_time": item.activation_time.value,
            "cooldown": item.cooldown.value,
            "priority": item.priority,
        }
        if getattr(item, "effect_data", None):
            metadata["effect_data"] = item.effect_data
        _db_execute("""
            INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity)
            VALUES (%s, %s, %s, FALSE, %s::jsonb, %s)
            ON CONFLICT (user_id, buff_id) DO UPDATE
              SET buff_name = EXCLUDED.buff_name, metadata = EXCLUDED.metadata,
                  quantity = user_buffs.quantity + EXCLUDED.quantity
        """, (user_id, item.item_id, item.name, json.dumps(metadata), qty))
        lines.append(f"📦 {getattr(item, 'emoji', '')} {item.name} x{qty}")

    # Зворотна сумісність: старі записи/конфіг могли містити subscription_days.
    sub_days = rewards.get("game_vip_days") or rewards.get("subscription_days") or 0
    if sub_days > 0:
        now = datetime.now()
        end_date = now + timedelta(days=sub_days)
        row = _db_fetchone(
            "SELECT user_id, subscription_type, subscription_end FROM subscriptions WHERE user_id = %s",
            (user_id,),
        )
        if row:
            current_type = (row[1] or "").strip()
            current_end = row[2]
            if current_end and current_end > now:
                end_date = max(current_end, end_date)
            # Адвент видає саме VIP+.
            next_type = "vip_plus_30"
            _db_execute("""
                UPDATE subscriptions
                SET subscription_type = %s, subscription_end = %s, is_active = TRUE, updated_at = %s
                WHERE user_id = %s
            """, (next_type, end_date, now, user_id))
        else:
            _db_execute("""
                INSERT INTO subscriptions (user_id, subscription_type, subscription_start, subscription_end, is_active, is_purchased)
                VALUES (%s, 'vip_plus_30', %s, %s, TRUE, FALSE)
            """, (user_id, now, end_date))
        lines.append(f"🎫 VIP+ +{sub_days} днів")

    if lines:
        conn.commit()
    return lines


def build_buff_choice_keyboard(day_number: int) -> InlineKeyboardMarkup:
    """Клавіатура вибору одного бафа в подарунок (день з buff_choice). Callback: advent_ch_<day>_<buff_id>."""
    builder = InlineKeyboardBuilder()
    for buff_id, item in (BUFF_ITEMS or {}).items():
        # Не пропонуємо «Прохід у портал» як подарунковий баф з адвенту
        if buff_id == "portal_pass":
            continue
        emoji = getattr(item, "emoji", "📦")
        name = getattr(item, "name", buff_id)
        # callback_data обмеження 64 байти; buff_id може містити _
        builder.button(text=f"{emoji} {name}", callback_data=f"advent_ch_{day_number}_{buff_id}")
    builder.adjust(2)  # по 2 кнопки в ряд
    return builder.as_markup()


def has_buff_choice_for_day(day_number: int) -> bool:
    return bool((ADVENT_REWARDS.get(day_number) or {}).get("buff_choice"))


def user_already_chose_buff(user_id: int, day_number: int) -> bool:
    row = _db_fetchone(
        "SELECT 1 FROM advent_buff_choice WHERE user_id = %s AND event_key = %s AND day_number = %s",
        (user_id, EVENT_KEY, day_number),
    )
    return row is not None


def grant_advent_buff_choice(user_id: int, buff_id: str, quantity: int = 1) -> bool:
    """Видає один баф користувачу (як при buff_choice). Повертає True при успіху."""
    item = (BUFF_ITEMS or {}).get(buff_id)
    if not item:
        return False
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
        _db_execute("""
            INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity)
            VALUES (%s, %s, %s, FALSE, %s::jsonb, %s)
            ON CONFLICT (user_id, buff_id) DO UPDATE
              SET buff_name = EXCLUDED.buff_name, metadata = EXCLUDED.metadata,
                  quantity = user_buffs.quantity + EXCLUDED.quantity
        """, (user_id, item.item_id, item.name, json.dumps(metadata), quantity))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


def build_calendar_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавіатура: відкриті - ✓ N; сьогодні (якщо ще не відкрито) - 🌸 N; решта - 🔒."""
    opened = get_opened_days(user_id)
    today = get_today_day()
    can_open = can_open_today(user_id)  # день, який сьогодні можна відкрити, або None
    unlocked = get_unlocked_days(user_id)
    builder = InlineKeyboardBuilder()
    for day in DAYS_LIST:
        if day in opened:
            builder.button(text=f"✓ {day}", callback_data=f"advent_{EVENT_KEY}_{day}_done")
        elif day == can_open:
            builder.button(text=f"🌸 {day}", callback_data=f"advent_{EVENT_KEY}_{day}")
        elif day in unlocked:
            builder.button(text=f"🌸 {day}", callback_data=f"advent_{EVENT_KEY}_{day}")
        else:
            builder.button(text="🔒", callback_data=f"advent_{EVENT_KEY}_{day}_lock")
    builder.adjust(5)  # 5 кнопок в ряд (31 день = 6 рядів по 5 + 1 кнопка)
    return builder.as_markup()


def _is_before_advent() -> bool:
    now = datetime.now()
    return (now.month, now.day) < (ADVENT_START_MONTH, ADVENT_START_DAY)


def _is_after_advent() -> bool:
    now = datetime.now()
    return (now.month, now.day) > (ADVENT_END_MONTH, ADVENT_END_DAY)


def get_calendar_text(user_id: int) -> str:
    opened = get_opened_days(user_id)
    today = get_today_day()
    can_open = can_open_today(user_id)
    count = len(opened)
    if not is_advent_active():
        if _is_before_advent():
            progress = f"⏳ Адвент ще не почався. Весняний адвент проходить <b>{ADVENT_DATE_DESC}</b>. Зачекай на старт!"
        else:
            progress = "✅ Адвент закінчився. Дякуємо за участь!"
        return (
            "🌿 <b>Весняний адвент-календар</b> 🌿\n\n"
            f"День <b>N</b> можна відкрити лише <b>N</b>-го числа в період адвенту. "
            "Пропустив день - відкрити його вже не можна.\n\n"
            f"{progress}\n\nВідкрито: <b>{count}/{TOTAL_DAYS}</b>."
        )
    if count == TOTAL_DAYS:
        progress = f"✅ Усі <b>{TOTAL_DAYS}</b> днів відкрито. Дякуємо, що йшов усім шляхом."
    elif can_open is not None:
        progress = f"Відкрито: <b>{count}/{TOTAL_DAYS}</b>. Сьогодні ({today}-го) можна відкрити день <b>{today}</b> - натисни 🌸."
    else:
        if today is not None and today not in opened and FIRST_DAY <= today <= LAST_DAY:
            progress = f"Відкрито: <b>{count}/{TOTAL_DAYS}</b>. Сьогоднішній день ти вже відкрив."
        else:
            next_d = (today or 0) + 1
            progress = f"Відкрито: <b>{count}/{TOTAL_DAYS}</b>. Наступний день - <b>{next_d}</b>-го числа."
    return (
        "🌿 <b>Весняний адвент-календар</b> 🌿\n\n"
        f"Адвент проходить <b>{ADVENT_DATE_DESC}</b>. День <b>N</b> відкривається <b>N</b>-го числа. "
        "Пропустив день - відкрити вже не можна.\n\n"
        f"{progress}"
    )


@router_advent.message(Command("advent"))
async def cmd_advent(message: Message):
    """Показати адвент-календар в ПП; у групах дати підказку."""
    # Якщо команда прийшла не з ЛС - пояснюємо, що її треба викликати в особистих.
    if message.chat and message.chat.type != "private":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🌿 Відкрити адвент у ПП",
                        url="https://t.me/sicilian_mafia_bot?start=advent",
                    )
                ]
            ]
        )
        await message.answer(
            "🌿 Весняний адвент-календар доступний тільки в особистих повідомленнях з ботом.",
            reply_markup=kb,
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    if not user_id:
        return
    try:
        text = get_calendar_text(user_id)
        keyboard = build_calendar_keyboard(user_id)
    except Exception:
        # Якщо щось пішло не так (наприклад, проблема з БД) - не мовчимо.
        await message.answer(
            "🌿 Весняний адвент-календар тимчасово недоступний.\n"
            "Спробуй трохи пізніше або напиши засновнику, щоб він перевірив налаштування.",
            parse_mode="html",
        )
        return
    await message.answer(text, reply_markup=keyboard, parse_mode="html")


@router_advent.message(Command("advent_unlock"), F.chat.type == "private")
async def cmd_advent_unlock(message: Message):
    """Власник: видати доступ користувачу до конкретного дня адвенту.

    Використання: /advent_unlock <user_id> <day>
    """
    if message.from_user is None or message.from_user.id not in BOT_OWNER_IDS:
        return
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 3:
        await message.answer("Використання: <code>/advent_unlock &lt;user_id&gt; &lt;day(1-31)&gt;</code>", parse_mode="html")
        return
    try:
        target_id = int(parts[1])
        day_num = int(parts[2])
    except ValueError:
        await message.answer("❌ Невірні параметри. Приклад: <code>/advent_unlock 123456789 5</code>", parse_mode="html")
        return
    if day_num < FIRST_DAY or day_num > LAST_DAY:
        await message.answer("❌ День має бути в межах 1–31.", parse_mode="html")
        return
    opened = get_opened_days(target_id)
    if day_num in opened:
        await message.answer("ℹ️ Цей день вже відкритий у користувача.", parse_mode="html")
        return
    if grant_unlock_day(target_id, day_num, message.from_user.id):
        await message.answer(
            f"✅ Видано доступ: user_id=<code>{target_id}</code>, день <b>{day_num}</b>.\n"
            f"Користувач зможе відкрити його в /advent (кнопка 🌸).",
            parse_mode="html",
        )
    else:
        await message.answer("❌ Не вдалося видати доступ (помилка БД).", parse_mode="html")


@router_advent.callback_query(F.data.startswith(f"advent_{EVENT_KEY}_"))
async def advent_callback(callback: CallbackQuery):
    """Обробка натискання на клітинку: відкрити день або показати підказку."""
    user_id = callback.from_user.id if callback.from_user else 0
    if not user_id:
        await callback.answer()
        return
    data = callback.data or ""
    # advent_spring_2025_<N> або advent_spring_2025_<N>_done / _lock
    parts = data.split("_")
    if len(parts) < 4:
        await callback.answer()
        return
    try:
        day_num = int(parts[3])
    except ValueError:
        await callback.answer()
        return
    if day_num < FIRST_DAY or day_num > LAST_DAY:
        await callback.answer()
        return

    if not is_advent_active():
        await callback.answer(
            f"Адвент зараз не активний. Весняний адвент - {ADVENT_DATE_DESC}.",
            show_alert=True,
        )
        return

    today = get_today_day()
    opened = get_opened_days(user_id)
    unlocked = get_unlocked_days(user_id)

    if data.endswith("_done"):
        await callback.answer("Цей день ти вже відкрив.", show_alert=False)
        return
    if data.endswith("_lock"):
        if day_num < today:
            await callback.answer("Цей день вже минув. Пропустив - відкрити не можна.", show_alert=True)
        elif day_num > today:
            await callback.answer(f"Цей день відкривається {day_num}-го числа місяця. Зачекай.", show_alert=True)
        else:
            await callback.answer("Сьогодні можна відкрити цей день - натисни на кнопку з 🌸.", show_alert=False)
        return

    # Відкрити можна лише сьогоднішній день, або день який розблокував власник
    if day_num != today and day_num not in unlocked:
        if day_num < today:
            await callback.answer("Ти пропустив цей день. Його вже не відкрити.", show_alert=True)
        else:
            await callback.answer(f"День {day_num} відкривається {day_num}-го числа. Сьогодні {today}-е.", show_alert=True)
        return
    if day_num in opened:
        await callback.answer("Сьогоднішній день ти вже відкрив.", show_alert=False)
        return

    if not open_day(user_id, day_num):
        await callback.answer("Не вдалося відкрити. Спробуй ще раз.", show_alert=True)
        return

    # Якщо день було відкрито через адмін-доступ - “спалюємо” розблокування
    if day_num in unlocked:
        consume_unlock_day(user_id, day_num)

    # З шансом 1% випадає унікальна карточка «Клоун» (попадає в /cards)
    clown_dropped = False
    if random.randint(1, 100) == 1:
        clown_dropped = grant_clown_card_to_user(user_id)

    reward_lines = apply_advent_rewards(user_id, day_num)
    day_text = DAY_TEXTS.get(day_num, f"День {day_num}.")
    opened_count = len(get_opened_days(user_id))
    body = f"🌸 <b>День {day_num} відкрито</b>\n\n{day_text}"
    if reward_lines:
        body += f"\n\n<b>Нагороди:</b>\n" + "\n".join(reward_lines)
    if has_buff_choice_for_day(day_num):
        body += "\n\n📦 <b>Обери один баф у подарунок</b> - натисни кнопку нижче."
    if clown_dropped:
        body += "\n\n🎭 <b>Тобі випала унікальна карточка «Клоун»!</b> Вона вже у твоїй колекції - /cards"
    body += f"\n\n<i>Прогрес: {opened_count}/{TOTAL_DAYS}</i>"
    await callback.answer("Відкрито!", show_alert=False)
    await callback.message.answer(emoji_to_premium(body), parse_mode="html")
    # Якщо випала картка Клоун - відправляємо відео та повний сюжет
    if clown_dropped and callback.bot:
        await _send_clown_story_to_user(callback.bot, user_id)
    # Якщо цей день з вибором бафа - одразу показуємо клавіатуру вибору
    if has_buff_choice_for_day(day_num):
        await callback.message.answer(
            "📦 Обери один баф у подарунок:",
            reply_markup=build_buff_choice_keyboard(day_num),
            parse_mode="html",
        )
    # Оновлюємо календар у тому ж повідомленні
    new_text = get_calendar_text(user_id)
    new_kb = build_calendar_keyboard(user_id)
    try:
        await callback.message.edit_text(new_text, reply_markup=new_kb, parse_mode="html")
    except Exception:
        pass


@router_advent.callback_query(F.data.startswith("advent_ch_"))
async def advent_buff_choice_callback(callback: CallbackQuery):
    """Обробка вибору бафа в подарунок (день з buff_choice). Callback: advent_ch_<day>_<buff_id>."""
    user_id = callback.from_user.id if callback.from_user else 0
    if not user_id:
        await callback.answer()
        return
    data = (callback.data or "").strip()
    parts = data.split("_")
    if len(parts) < 4:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    try:
        day_num = int(parts[2])
    except ValueError:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    buff_id = "_".join(parts[3:])
    if not buff_id or day_num < FIRST_DAY or day_num > LAST_DAY:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    if not has_buff_choice_for_day(day_num):
        await callback.answer("Для цього дня вибір бафа недоступний.", show_alert=True)
        return
    # Перевірка: користувач відкрив цей день
    opened = get_opened_days(user_id)
    if day_num not in opened:
        await callback.answer("Спочатку відкрий цей день в календарі.", show_alert=True)
        return
    if user_already_chose_buff(user_id, day_num):
        await callback.answer("Ти вже обрав баф для цього дня.", show_alert=True)
        return
    item = (BUFF_ITEMS or {}).get(buff_id)
    if not item:
        await callback.answer("Такий баф не знайдено.", show_alert=True)
        return
    try:
        _db_execute(
            "INSERT INTO advent_buff_choice (user_id, event_key, day_number, buff_id) VALUES (%s, %s, %s, %s)",
            (user_id, EVENT_KEY, day_num, buff_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        await callback.answer("Помилка збереження. Спробуй ще раз.", show_alert=True)
        return
    if not grant_advent_buff_choice(user_id, buff_id, 1):
        await callback.answer("Не вдалося видати баф.", show_alert=True)
        return
    name = getattr(item, "name", buff_id)
    await callback.answer(f"Ти обрав: {name}", show_alert=False)
    try:
        await callback.message.edit_text(
            f"📦 <b>Ти обрав баф:</b> {name}\n\nВін доданий до твоїх предметів.",
            parse_mode="html",
        )
    except Exception:
        pass
