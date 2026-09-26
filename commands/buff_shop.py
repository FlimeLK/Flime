import os
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from database.database import (
    cursor, conn, get_group_buff_settings,
    has_portal_access, grant_portal_access, revoke_portal_access, get_portal_progress, set_portal_completed,
    run_db_call_async,
)
from commands.start import add_user_to_db
from premium_emoji import emoji_to_premium, custom_emoji_id_for_symbol

# ID головного власника бота
BOT_OWNER_ID = 1859870653

# Обмінник: 1 золото = 100 лір
GOLD_TO_KRB_RATE = 100
# Світ має ціну: продаж бафів назад у ліри (комісія обмінника): 63.33% від ціни (приклад: 150 -> 95)
BUFF_SELL_RATE = 95 / 150


router_buff_shop = Router()


def _db_fetchone_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute_sync(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0


def _db_commit_sync() -> None:
    conn.commit()


# ============================================================================
# ВИЗНАЧЕННЯ КЛАСІВ ТА СТРУКТУР
# ============================================================================

class ItemCategory(Enum):
    CHEAP = "cheap"      # 🟢 Дешеві
    EXPENSIVE = "expensive"  # 🟡 Дорогі
    ULTRA = "ultra"      # 🔴 Ультра


class ItemType(Enum):
    ACTIVE = "active"    # Активний (кнопка)
    PASSIVE = "passive"  # Пасивний (автоматично)
    AUTO = "auto"        # Авто (без вибору гравця)


class ActivationTime(Enum):
    DAY = "day"
    NIGHT = "night"
    ANY_PHASE = "any_phase"  # день або ніч (кнопка в обох фазах)
    AFTER_NIGHT = "after_night"
    AFTER_DEATH = "after_death"


class CooldownType(Enum):
    ONCE = "once"                    # 1 раз
    ONCE_PER_GAME = "once_per_game"  # 1 раз за гру
    ONCE_PER_NIGHT = "once_per_night"  # 1 раз за ніч
    PERMANENT = "permanent"          # Постійно
    ONCE_PER_EVENT = "once_per_event"  # Одноразово за івент


@dataclass(frozen=True)
class ItemDefinition:
    item_id: str
    emoji: str
    name: str
    category: ItemCategory
    price: int  # ліри
    description: str
    item_type: ItemType
    activation_time: ActivationTime
    cooldown: CooldownType
    priority: int = 0  # Пріоритет обробки (вищий = раніше)
    effect_data: Optional[Dict] = None  # Додаткові дані ефекту
    shop_hidden: bool = False  # True = не показувати в магазині (напр. крафт-бафи івентів)


# ============================================================================
# КАТАЛОГ ПРЕДМЕТІВ
# ============================================================================

# Новий каталог предметів чорного ринку (без категорій у UI)
ITEMS: Dict[str, ItemDefinition] = {
    "tommy_gun": ItemDefinition(
        item_id="tommy_gun",
        emoji="🔫",
        name="Tommy Gun",
        category=ItemCategory.CHEAP,
        price=320,
        description="Відбиває напад на тебе - атакуючий гине замість цілі.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.AFTER_DEATH,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=6,
        effect_data={"effect": "kill_killer_on_death"},
    ),
    "knife": ItemDefinition(
        item_id="knife",
        emoji="🔪",
        name="Заточка",
        category=ItemCategory.CHEAP,
        price=400,
        description="Дозволяє вбити будь-якого гравця незалежно від ролі.",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=1,
        effect_data={"effect": "direct_kill"},
    ),
    "black_opel": ItemDefinition(
        item_id="black_opel",
        emoji="🚗",
        name="Чорний «Опель»",
        category=ItemCategory.CHEAP,
        price=340,
        description="Дає можливість уникнути страти під час голосування.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.DAY,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=2,
        effect_data={"effect": "prevent_lynch"},
    ),
    "capone_hat": ItemDefinition(
        item_id="capone_hat",
        emoji="🎩",
        name="Капелюх КаПоне",
        category=ItemCategory.CHEAP,
        price=280,
        description="Робить тебе недоступним для вбивства, перевірки та дій активних ролей на одну ніч.",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.DAY,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=1,
        effect_data={"effect": "invisible_to_night_actions"},
    ),
    "flashlight_new": ItemDefinition(
        item_id="flashlight_new",
        emoji="🔦",
        name="Ліхтарик",
        category=ItemCategory.CHEAP,
        price=200,
        description="Якщо тебе вбили, наступного ранку показує, хто це зробив.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.AFTER_DEATH,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=6,
        effect_data={"effect": "reveal_killer"},
    ),
    "parfum": ItemDefinition(
        item_id="parfum",
        emoji="🧴",
        name="Парфум",
        category=ItemCategory.CHEAP,
        price=150,
        description="Різкий запах дешевого парфуму відлякує Коханку.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=1,
        effect_data={"effect": "repel_prostitute"},
    ),
    "black_cat": ItemDefinition(
        item_id="black_cat",
        emoji="🐈‍⬛",
        name="Чорний кіт",
        category=ItemCategory.CHEAP,
        price=175,
        description="Може занюхати гравця з активним парфумом і таємно донести цю інформацію лише Коханці. Повністю захищає Коханку від усіх ефектів парфуму.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=2,
        effect_data={"effect": "black_cat"},
    ),
    "talisman": ItemDefinition(
        item_id="talisman",
        emoji="📿",
        name="Талісман",
        category=ItemCategory.CHEAP,
        price=250,
        description="Кажуть, він береже від фатального пострілу.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.AFTER_DEATH,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "prevent_death_once"},
    ),
    "fox_passport": ItemDefinition(
        item_id="fox_passport",
        emoji="📜",
        name="Паспорт Лиса",
        category=ItemCategory.CHEAP,
        price=220,
        description="Фальшивий паспорт збиває зі сліду тих, хто надто цікавиться чужими справами. Якщо цієї ночі хтось спробує перевірити твою роль - перевірка не спрацює.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=2,
        effect_data={"effect": "block_role_check"},
    ),
    # ── Крафт-бафи івенту «Купальська ніч» (не продаються — лише через /kupala) ──
    "wreath_lucky": ItemDefinition(
        item_id="wreath_lucky",
        emoji="💮",
        name="Вінок «Щаслива ніч»",
        category=ItemCategory.CHEAP,
        price=0,
        description="Якщо ти Аль Капоне — цієї гри б'єш наосліп (можеш зачепити й своїх).",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=1,
        effect_data={"effect": "lucky_night"},
        shop_hidden=True,
    ),
    "wreath_magic": ItemDefinition(
        item_id="wreath_magic",
        emoji="🔮",
        name="Вінок «Магія Купала»",
        category=ItemCategory.CHEAP,
        price=0,
        description="50% шанс відбити кожну спрямовану на тебе нічну дію + бонусна квітка.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=1,
        effect_data={"effect": "kupala_magic"},
        shop_hidden=True,
    ),
}

# Унікальні бафи (нагороди з порталу). Не продаються в магазині; видаються після проходження сюжету порталу.
# У грі працюють тільки якщо в групі увімкнено «Тільки унікальні бафи».
UNIQUE_BUFFS: Dict[str, ItemDefinition] = {
    "portal_perfume_gucci": ItemDefinition(
        item_id="portal_perfume_gucci",
        emoji="✨",
        name="Пальоні парфуми Gucci",
        category=ItemCategory.ULTRA,
        price=0,
        description="«Ефект шлейфу»: Настільки сильний аромат, що Комісар \"чхає\" і помилково перевіряє випадкового гравця поруч із вами замість вас.",
        item_type=ItemType.PASSIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "portal_perfume_gucci"},
    ),
    "portal_ribbon": ItemDefinition(
        item_id="portal_ribbon",
        emoji="🎀",
        name="Кольорова стрічка",
        category=ItemCategory.ULTRA,
        price=0,
        description="«Мітка своїх»: Ви пов'язуєте стрічку на іншого гравця. Якщо цієї ночі його намагатимуться вбити, він виживе, але ви втратите цей баф назавжди.",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "portal_ribbon"},
    ),
    "portal_seeds": ItemDefinition(
        item_id="portal_seeds",
        emoji="🌻",
        name="Стаканчик насіння",
        category=ItemCategory.ULTRA,
        price=0,
        description="«Заговорити зуби»: Ви обираєте гравця, з яким «лускаєте насіння». Ця людина пропускає нічне голосування або використання своєї ролі, бо була надто зайнята розмовами.",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "portal_seeds"},
    ),
    "portal_spirit_2021": ItemDefinition(
        item_id="portal_spirit_2021",
        emoji="🌊",
        name="Дух 2021",
        category=ItemCategory.ULTRA,
        price=0,
        description="«Ковідна ізоляція»: Ви відправляєте гравця на самоізоляцію. Він не може ні на кого впливати, але й ніхто не може вплинути на нього (повний імунітет на ніч).",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "portal_spirit_2021"},
    ),
    "portal_smell_fry": ItemDefinition(
        item_id="portal_smell_fry",
        emoji="🍟",
        name="Запах фрі",
        category=ItemCategory.ULTRA,
        price=0,
        description="«Фастфуд-пастка»: Ви залишаєте «запах» біля іншого гравця. Всі, хто прийдуть до нього вночі (вбивці, лікар, Комісар), замість своєї дії просто «купують картоплю» і нічого не роблять.",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "portal_smell_fry"},
    ),
    "portal_kyiv_taste": ItemDefinition(
        item_id="portal_kyiv_taste",
        emoji="🍰",
        name="Київський смак",
        category=ItemCategory.ULTRA,
        price=0,
        description="«Солодкий підкуп»: Ви пригощаєте гравця шматочком торта. Якщо завтра на голосуванні він захоче проголосувати проти вас, його голос анулюється.",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.NIGHT,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "portal_kyiv_taste"},
    ),
    "devil_covenant": ItemDefinition(
        item_id="devil_covenant",
        emoji="💥",
        name="Контракт з дияволом",
        category=ItemCategory.ULTRA,
        price=0,
        description="Кажуть, угоди такого рівня не укладають просто так. Один день і одну ніч жодна ворожа дія проти тебе не спрацює. Один раз за гру. Не продається - нагорода за перемогу Диявола або виконавця контракту.",
        item_type=ItemType.ACTIVE,
        activation_time=ActivationTime.ANY_PHASE,
        cooldown=CooldownType.ONCE_PER_GAME,
        priority=5,
        effect_data={"effect": "devil_covenant_shield"},
    ),
}

# ID унікальних бафів квесту порталу (без нагородних бафів на кшталт «Контракт з дияволом»)
PORTAL_QUEST_REWARD_IDS = [
    "portal_perfume_gucci",
    "portal_ribbon",
    "portal_seeds",
    "portal_spirit_2021",
    "portal_smell_fry",
    "portal_kyiv_taste",
]


def _unique_buff_profile_order() -> List[str]:
    """Порядок у «Мої бафи» → Унікальні: спочатку нагороди порталу, потім інші з UNIQUE_BUFFS."""
    order: List[str] = []
    seen: Set[str] = set()
    for bid in PORTAL_QUEST_REWARD_IDS:
        if bid in UNIQUE_BUFFS and bid not in seen:
            order.append(bid)
            seen.add(bid)
    for bid in sorted(UNIQUE_BUFFS.keys()):
        if bid not in seen:
            order.append(bid)
            seen.add(bid)
    return order


# Видаляємо з інвентаря бафи, яких немає в каталозі (ITEMS) та в унікальних (UNIQUE_BUFFS). Унікальні не видаляємо.
def _cleanup_removed_buffs():
    try:
        valid_ids = list(ITEMS.keys()) + list(UNIQUE_BUFFS.keys())
        if not valid_ids:
            return
        placeholders = ",".join(["%s"] * len(valid_ids))
        _db_execute_sync(
            f"DELETE FROM user_buffs WHERE buff_id NOT IN ({placeholders})",
            valid_ids
        )
        _db_commit_sync()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

# Ліміт активних бафів більше не використовується (без обмежень по кількості).
# MAX_ULTRA_ITEMS_PER_GAME залишено тільки для можливого майбутнього використання.
MAX_ITEMS_PER_PLAYER = 9999
MAX_ULTRA_ITEMS_PER_GAME = 1
# ЕКСПОРТОВАНІ ФУНКЦІЇ ДЛЯ ІНТЕГРАЦІЇ З ІГРОВИМ ПРОЦЕСОМ
# ============================================================================

def is_buff_allowed_in_chat(chat_id: Optional[int], buff_id: str) -> bool:
    """
    Чи дозволено використовувати баф у цій групі.
    Якщо chat_id None - дозволено. Інакше перевіряє group_buff_settings.
    """
    if chat_id is None:
        return True
    enabled, disabled, _ = get_group_buff_settings(chat_id)
    if not enabled:
        return False
    return buff_id not in disabled


def _user_has_unique_buff(user_id: int, buff_id: str) -> bool:
    """Чи має користувач цей баф як унікальний (з порталу)."""
    row = _db_fetchone_sync(
        "SELECT 1 FROM user_buffs WHERE user_id = %s AND buff_id = %s AND COALESCE(is_unique, FALSE) = TRUE AND (COALESCE(infinite, FALSE) = TRUE OR COALESCE(quantity, 1) > 0)",
        (user_id, buff_id),
    )
    return row is not None


def try_consume_buff(chat_id: Optional[int], user_id: int, buff_id: str) -> bool:
    """
    Списує використання бафа тільки якщо баф дозволений у групі.
    У режимі «тільки унікальні бафи» звичайні бафи не працюють.
    Повертає True якщо списання виконано, False інакше.
    """
    if not is_buff_allowed_in_chat(chat_id, buff_id):
        return False
    return consume_buff_use(user_id, buff_id)


def get_active_items_for_player(user_id: int, chat_id: Optional[int] = None) -> List[Dict]:
    """
    Повертає список активних предметів гравця з усією інформацією.
    Тільки рядки з quantity > 0 (бафи куплені по кількості, кожне використання в грі зменшує quantity).
    
    Returns:
        List[Dict] з ключами: item_id, name, category, item_type, activation_time, 
        cooldown, priority, effect_data, is_active, quantity
    """
    rows = _db_fetchall_sync("""
        SELECT buff_id, buff_name, COALESCE(is_active, FALSE), metadata, COALESCE(quantity, 1), COALESCE(infinite, FALSE), COALESCE(is_unique, FALSE)
        FROM user_buffs
        WHERE user_id = %s AND COALESCE(is_active, FALSE) = TRUE AND (COALESCE(infinite, FALSE) = TRUE OR COALESCE(quantity, 1) > 0)
        ORDER BY COALESCE((metadata->>'priority')::int, 0) DESC
    """, (user_id,))
    rows = rows or []

    result = []
    for row in rows:
        if len(row) >= 7:
            buff_id, name, is_active, metadata_json, quantity, infinite, is_unique = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
        else:
            buff_id, name, is_active, metadata_json, quantity, infinite = row[0], row[1], row[2], row[3], row[4], row[5]
            is_unique = False
        if chat_id is not None and not is_buff_allowed_in_chat(chat_id, buff_id):
            continue
        item = ITEMS.get(buff_id) or UNIQUE_BUFFS.get(buff_id)
        if not item:
            continue
        
        metadata = metadata_json if isinstance(metadata_json, dict) else {}
        result.append({
            "item_id": buff_id,
            "name": name,
            "category": item.category,
            "item_type": item.item_type,
            "activation_time": item.activation_time,
            "cooldown": item.cooldown,
            "priority": item.priority,
            "effect_data": item.effect_data or {},
            "is_active": bool(is_active),
            "quantity": int(quantity),
            "infinite": bool(infinite),
            "metadata": metadata
        })
    
    return result


def consume_buff_use(user_id: int, buff_id: str) -> bool:
    """
    Списує одне використання бафа (один «заряд»). Викликати після реального застосування ефекту в грі.
    Безкінечні бафи (infinite=TRUE) не зменшують quantity - завжди повертає True.
    Returns True якщо списання виконано (або баф безкінечний), False якщо немає зарядів або запису.
    """
    # Баф має бути УВІМКНЕНИЙ (is_active=TRUE), інакше він не повинен спрацьовувати.
    row = _db_fetchone_sync(
        "SELECT COALESCE(infinite, FALSE) FROM user_buffs WHERE user_id = %s AND buff_id = %s AND COALESCE(is_active, FALSE) = TRUE",
        (user_id, buff_id),
    )
    if not row:
        return False
    if row[0]:  # infinite - не списуємо, просто успіх
        return True
    row = _db_fetchone_sync("""
        UPDATE user_buffs
        SET quantity = quantity - 1
        WHERE user_id = %s AND buff_id = %s AND COALESCE(is_active, FALSE) = TRUE AND COALESCE(quantity, 1) > 0
        RETURNING quantity
    """, (user_id, buff_id))
    if row:
        _db_commit_sync()
        return True
    return False


def grant_portal_reward(user_id: int, unique_buff_id: str) -> bool:
    """
    Видає користувачу унікальний баф з порталу (запис у user_buffs з is_unique=TRUE).
    unique_buff_id має бути ключем з UNIQUE_BUFFS. Повертає True при успіху.
    """
    item = UNIQUE_BUFFS.get(unique_buff_id)
    if not item:
        return False
    import json
    metadata = {
        "category": item.category.value,
        "item_type": item.item_type.value,
        "activation_time": item.activation_time.value,
        "cooldown": item.cooldown.value,
        "priority": item.priority,
    }
    if item.effect_data:
        metadata["effect_data"] = item.effect_data
    try:
        _db_execute_sync("""
            INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity, is_unique)
            VALUES (%s, %s, %s, TRUE, %s::jsonb, 1, TRUE)
            ON CONFLICT (user_id, buff_id) DO UPDATE SET
                buff_name = EXCLUDED.buff_name, metadata = EXCLUDED.metadata,
                quantity = GREATEST(user_buffs.quantity, 1), is_active = TRUE, is_unique = TRUE
        """, (user_id, unique_buff_id, item.name, json.dumps(metadata)))
        _db_commit_sync()
        return True
    except Exception as e:
        logging.getLogger(__name__).exception(
            "grant_portal_reward failed: user_id=%s buff_id=%s: %s", user_id, unique_buff_id, e
        )
        try:
            conn.rollback()
        except Exception:
            pass
    return False


def admin_grant_buff_to_user(user_id: int, buff_id: str) -> Tuple[bool, str]:
    """
    Адмінська видача одного бафа (засновник → собі або тест).
    Унікальні бафи (UNIQUE_BUFFS) - через grant_portal_reward.
    Звичайні (ITEMS) - +1 заряд, is_active=TRUE.
    Повертає (успіх, повідомлення для людини: назва або текст помилки).
    """
    import json

    bid = (buff_id or "").strip()
    if not bid:
        return False, "Вкажи buff_id, наприклад: devil_covenant"

    if bid in UNIQUE_BUFFS:
        if grant_portal_reward(user_id, bid):
            return True, UNIQUE_BUFFS[bid].name
        return False, "Не вдалося записати унікальний баф у БД"

    item = ITEMS.get(bid)
    if not item:
        return False, f"Невідомий buff_id: {bid}"

    metadata = {
        "category": item.category.value,
        "item_type": item.item_type.value,
        "activation_time": item.activation_time.value,
        "cooldown": item.cooldown.value,
        "priority": item.priority,
    }
    if item.effect_data:
        metadata["effect_data"] = item.effect_data
    try:
        _db_execute_sync(
            """
            INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity, infinite, is_unique)
            VALUES (%s, %s, %s, TRUE, %s::jsonb, 1, FALSE, FALSE)
            ON CONFLICT (user_id, buff_id) DO UPDATE SET
                buff_name = EXCLUDED.buff_name,
                metadata = EXCLUDED.metadata,
                quantity = user_buffs.quantity + 1,
                is_active = TRUE,
                infinite = FALSE,
                is_unique = FALSE
            """,
            (user_id, item.item_id, item.name, json.dumps(metadata)),
        )
        _db_commit_sync()
        return True, item.name
    except Exception as e:
        logging.getLogger(__name__).exception("admin_grant_buff_to_user failed: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False, "Помилка БД при видачі бафа"


def _user_has_any_portal_buffs(user_id: int) -> bool:
    """Перевіряє, чи є у користувача хоча б один унікальний баф з порталу."""
    if not PORTAL_QUEST_REWARD_IDS:
        return False
    placeholders = ",".join(["%s"] * len(PORTAL_QUEST_REWARD_IDS))
    row = _db_fetchone_sync(
        f"SELECT 1 FROM user_buffs WHERE user_id = %s AND buff_id IN ({placeholders}) AND COALESCE(quantity, 1) > 0 LIMIT 1",
        (user_id,) + tuple(PORTAL_QUEST_REWARD_IDS),
    )
    return row is not None


def _get_missing_portal_buff_ids(user_id: int) -> List[str]:
    """Повертає список ID портальних бафів, яких у користувача немає (або quantity = 0)."""
    if not PORTAL_QUEST_REWARD_IDS:
        return []
    placeholders = ",".join(["%s"] * len(PORTAL_QUEST_REWARD_IDS))
    rows = _db_fetchall_sync(
        f"SELECT buff_id, COALESCE(quantity, 1) FROM user_buffs WHERE user_id = %s AND buff_id IN ({placeholders})",
        (user_id,) + tuple(PORTAL_QUEST_REWARD_IDS),
    )
    have = {row[0] for row in (rows or []) if int(row[1] or 0) > 0}
    return [bid for bid in PORTAL_QUEST_REWARD_IDS if bid not in have]


def grant_portal_quest_rewards(user_id: int) -> bool:
    """
    Видає всі нагороди квесту «З 1937-го до Макдаку 2021»: Дух 2021, Запах фрі, Київський смак.
    Повертає True, якщо хоча б один баф видано успішно.
    """
    ok = False
    for bid in PORTAL_QUEST_REWARD_IDS:
        if grant_portal_reward(user_id, bid):
            ok = True
    return ok


def grant_infinite_buffs_to_user(user_id: int) -> int:
    """
    Видає користувачу всі бафи з каталогу як безкінечні (infinite=TRUE, quantity=1).
    Використовується засновниками через /give_infinite_buffs.
    Повертає кількість оновлених/доданих записів.
    """
    import json
    count = 0
    for item_id, item in ITEMS.items():
        metadata = {
            "category": item.category.value,
            "item_type": item.item_type.value,
            "activation_time": item.activation_time.value,
            "cooldown": item.cooldown.value,
            "priority": item.priority,
        }
        if item.effect_data:
            metadata["effect_data"] = item.effect_data
        try:
            _db_execute_sync("""
                INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity, infinite)
                VALUES (%s, %s, %s, TRUE, %s::jsonb, 1, TRUE)
                ON CONFLICT (user_id, buff_id) DO UPDATE SET
                    buff_name = EXCLUDED.buff_name, metadata = EXCLUDED.metadata,
                    quantity = 1, infinite = TRUE, is_active = TRUE
            """, (user_id, item_id, item.name, json.dumps(metadata)))
            count += 1
        except Exception:
            pass
    try:
        _db_commit_sync()
    except Exception:
        conn.rollback()
    return count


def can_use_item(user_id: int, item_id: str) -> Tuple[bool, Optional[str]]:
    """
    Перевіряє, чи може гравець використати предмет (перевірка кулдауну).
    
    Returns:
        (can_use: bool, reason: Optional[str])
    """
    item = ITEMS.get(item_id) or UNIQUE_BUFFS.get(item_id)
    if not item:
        return False, "Предмет не знайдено"
    
    # Перевірка кулдауну (TODO: реалізувати повну логіку кулдаунів)
    # Поки що просто перевіряємо чи активний
    row = _db_fetchone_sync("""
        SELECT COALESCE(is_active, FALSE) FROM user_buffs
        WHERE user_id = %s AND buff_id = %s
    """, (user_id, item_id))
    if not row or not row[0]:
        return False, "Предмет не активовано"
    
    # Перевірка кількості зарядів або безкінечний баф
    qrow = _db_fetchone_sync(
        "SELECT COALESCE(quantity, 1), COALESCE(infinite, FALSE) FROM user_buffs WHERE user_id = %s AND buff_id = %s",
        (user_id, item_id),
    )
    if not qrow:
        return False, "Немає зарядів"
    qty, infinite = int(qrow[0] or 0), bool(qrow[1])
    if not infinite and qty <= 0:
        return False, "Немає зарядів"
    # TODO: Додати перевірку кулдаунів через окрему таблицю або metadata
    return True, None




def _get_balance(user_id: int) -> int:
    row = _db_fetchone_sync("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
    return int(row[0]) if row else 0


def _get_donate_balance(user_id: int) -> int:
    """
    Золоті монети (донат-валюта).
    Залишено для сумісності, але більше не використовується для купівлі бафів.
    """
    row = _db_fetchone_sync("SELECT COALESCE(donate_coins, 0) FROM users WHERE id = %s", (user_id,))
    return int(row[0]) if row else 0


def _ensure_user_wallet_row(user_id: int, first_name: Optional[str] = None, username: Optional[str] = None) -> None:
    """Гарантує, що в users є рядок для гаманця (ліри/золото)."""
    _db_execute_sync(
        """
        INSERT INTO users (id, tg_name, link, balance, donate_coins)
        VALUES (%s, %s, %s, 0, 0)
        ON CONFLICT (id) DO NOTHING
        """,
        (int(user_id), (first_name or "").strip() or None, (username or "").strip() or None),
    )
    _db_commit_sync()


def _get_sell_price_for_item(item_id: str) -> int:
    item = ITEMS.get(item_id)
    if not item:
        return 0
    price = int(getattr(item, "price", 0) or 0)
    if price <= 0:
        return 0
    return max(1, int(round(price * BUFF_SELL_RATE)))


def _get_user_items_count(user_id: int) -> int:
    """Повертає кількість активних предметів у гравця (типів з quantity > 0 або infinite)"""
    row = _db_fetchone_sync("""
        SELECT COUNT(*) FROM user_buffs
        WHERE user_id = %s AND COALESCE(is_active, FALSE) = TRUE
          AND (COALESCE(infinite, FALSE) = TRUE OR COALESCE(quantity, 1) > 0)
    """, (user_id,))
    return int(row[0]) if row else 0


def _get_user_ultra_items_count(user_id: int, chat_id: Optional[int] = None) -> int:
    """Повертає кількість ультра-предметів у гравця (для перевірки ліміту 1 за гру)"""
    # Перевіряємо в активній грі, якщо chat_id передано
    # Поки що просто перевіряємо загальну кількість ультра-предметів
    _db_fetchone_sync("""
        SELECT COUNT(*) FROM user_buffs ub
        JOIN (SELECT DISTINCT buff_id FROM user_buffs WHERE user_id = %s) AS user_items
        ON ub.buff_id = user_items.buff_id
        WHERE ub.user_id = %s
        AND EXISTS (
            SELECT 1 FROM user_buffs ub2
            WHERE ub2.buff_id = ub.buff_id
            AND ub2.user_id = %s
        )
    """, (user_id, user_id, user_id))
    # Спрощена перевірка - пізніше можна розширити
    return 0  # TODO: реалізувати перевірку категорії через metadata


@router_buff_shop.message(Command("exchange_gold"))
async def exchange_gold_cmd(message: Message):
    """
    /exchange_gold <amount>
    Обмінює золоті монети на ліри за курсом 1:100.
    """
    if message.chat.type != "private":
        await message.answer("💱 Обмінник працює тільки в ЛС бота.")
        return
    if not message.from_user:
        return

    parts = (message.text or "").strip().split()
    if len(parts) != 2:
        await message.answer(
            emoji_to_premium(
                "💱 <b>Обмін золота</b>\n\n"
                "Використання: <code>/exchange_gold 5</code>\n"
                f"Курс: <b>1</b> 🪙 = <b>{GOLD_TO_KRB_RATE}</b> 💵"
            ),
            parse_mode="html",
        )
        return
    try:
        amount = int(parts[1])
    except ValueError:
        await message.answer("Вкажи число. Наприклад: /exchange_gold 5")
        return
    if amount <= 0:
        await message.answer("Кількість має бути більшою за 0.")
        return

    user_id = int(message.from_user.id)
    try:
        _ensure_user_wallet_row(
            user_id,
            first_name=getattr(message.from_user, "first_name", None),
            username=getattr(message.from_user, "username", None),
        )
        row = _db_fetchone_sync(
            "SELECT COALESCE(donate_coins, 0), COALESCE(balance, 0) FROM users WHERE id = %s FOR UPDATE",
            (user_id,),
        )
        gold = int(row[0]) if row else 0
        bal = int(row[1]) if row else 0
        if gold < amount:
            await message.answer(
                f"Недостатньо золота.\n\nЗараз: <b>{gold}</b> 🪙",
                parse_mode="html",
            )
            conn.rollback()
            return

        add_krb = amount * GOLD_TO_KRB_RATE
        _db_execute_sync(
            "UPDATE users SET donate_coins = donate_coins - %s, balance = balance + %s WHERE id = %s",
            (amount, add_krb, user_id),
        )
        _db_commit_sync()

        await message.answer(
            emoji_to_premium(
                "💱 <b>Обмін виконано</b>\n\n"
                f"Списано: <b>{amount}</b> 🪙\n"
                f"Нараховано: <b>{add_krb}</b> 💵\n\n"
                f"Новий баланс: <b>{bal + add_krb}</b> 💵"
            ),
            parse_mode="html",
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await message.answer("Не вдалося виконати обмін. Спробуй пізніше.")


@router_buff_shop.message(Command("sell_buff"))
async def sell_buff_cmd(message: Message):
    """
    /sell_buff <buff_id> [qty]
    Продає баф назад у ліри з комісією обмінника.
    """
    if message.chat.type != "private":
        await message.answer("🌍 Світ має ціну працює тільки в ЛС бота.")
        return
    if not message.from_user:
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.answer(
            emoji_to_premium(
                "🌍 <b>Світ має ціну</b>\n\n"
                "Використання: <code>/sell_buff knife 1</code>\n"
                "• <code>buff_id</code> - технічний ID бафа\n"
                "• <code>qty</code> - кількість (за замовчуванням 1)\n\n"
                "💡 Дивись наявні бафи в <code>/show_buff</code>."
            ),
            parse_mode="html",
        )
        return

    buff_id = parts[1].strip()
    qty = 1
    if len(parts) >= 3:
        try:
            qty = int(parts[2])
        except ValueError:
            await message.answer("Кількість має бути числом.")
            return
    if qty <= 0:
        await message.answer("Кількість має бути більшою за 0.")
        return

    item = ITEMS.get(buff_id)
    if not item:
        await message.answer("Невідомий баф. Перевір buff_id в /show_buff.")
        return

    sell_price_one = _get_sell_price_for_item(buff_id)
    if sell_price_one <= 0:
        await message.answer("Цей баф не можна продати в обміннику.")
        return

    user_id = int(message.from_user.id)
    try:
        _ensure_user_wallet_row(
            user_id,
            first_name=getattr(message.from_user, "first_name", None),
            username=getattr(message.from_user, "username", None),
        )
        row = _db_fetchone_sync(
            """
            SELECT COALESCE(quantity, 1), COALESCE(infinite, FALSE), COALESCE(is_unique, FALSE), COALESCE(balance, 0)
            FROM user_buffs ub
            JOIN users u ON u.id = ub.user_id
            WHERE ub.user_id = %s AND ub.buff_id = %s
            FOR UPDATE
            """,
            (user_id, buff_id),
        )
        if not row:
            conn.rollback()
            await message.answer("У тебе немає цього бафа.")
            return
        current_qty = int(row[0] or 0)
        is_infinite = bool(row[1])
        is_unique = bool(row[2])
        current_balance = int(row[3] or 0)

        if is_unique:
            conn.rollback()
            await message.answer("Унікальні бафи (портал) продати не можна.")
            return
        if is_infinite:
            conn.rollback()
            await message.answer("Безкінечні бафи продати не можна.")
            return
        if current_qty < qty:
            conn.rollback()
            await message.answer(f"Недостатньо кількості. У тебе: {current_qty}")
            return

        new_qty = current_qty - qty
        if new_qty > 0:
            _db_execute_sync(
                "UPDATE user_buffs SET quantity = %s WHERE user_id = %s AND buff_id = %s",
                (new_qty, user_id, buff_id),
            )
        else:
            _db_execute_sync("DELETE FROM user_buffs WHERE user_id = %s AND buff_id = %s", (user_id, buff_id))

        payout = sell_price_one * qty
        _db_execute_sync("UPDATE users SET balance = balance + %s WHERE id = %s", (payout, user_id))
        _db_commit_sync()

        await message.answer(
            emoji_to_premium(
                " <b>Продаж виконано</b>\n\n"
                f"Продано: <b>{item.name}</b> x{qty}\n"
                f"Нараховано: <b>{payout}</b> 💵\n"
                f"Ціна за 1: <b>{sell_price_one}</b> 💵\n\n"
                f"Новий баланс: <b>{current_balance + payout}</b> 💵"
            ),
            parse_mode="html",
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await message.answer("Не вдалося продати баф. Спробуй пізніше.")


def _get_user_buffs(user_id: int) -> List[Tuple[str, bool]]:
    """
    Returns list of (buff_name, is_active) for user.
    """
    rows = _db_fetchall_sync("""
        SELECT buff_name, COALESCE(is_active, FALSE)
        FROM user_buffs
        WHERE user_id = %s
        ORDER BY purchased_at ASC
    """, (user_id,))
    rows = rows or []
    return [(str(name), bool(active)) for (name, active) in rows]


def _get_user_buffs_detailed(user_id: int) -> List[Tuple[str, str, bool, Optional[str], int, bool]]:
    """
    Returns list of (buff_id, buff_name, is_active, category, quantity, infinite) for user.
    """
    rows = _db_fetchall_sync("""
        SELECT buff_id, buff_name, COALESCE(is_active, FALSE), 
               metadata->>'category', COALESCE(quantity, 1), COALESCE(infinite, FALSE)
        FROM user_buffs
        WHERE user_id = %s
        ORDER BY purchased_at ASC
    """, (user_id,))
    rows = rows or []
    result = []
    for (buff_id, name, active, cat, quantity, infinite) in rows:
        # Перевіряємо чи категорія валідна, якщо ні - беремо з ITEMS
        category_str = None
        if cat:
            # Перевіряємо чи це валідна категорія
            try:
                ItemCategory(cat)  # Перевірка чи валідна
                category_str = cat
            except (ValueError, TypeError):
                # Якщо не валідна, беремо з ITEMS
                item = ITEMS.get(str(buff_id))
                if item:
                    category_str = item.category.value
        else:
            # Якщо категорії немає в metadata, беремо з ITEMS
            item = ITEMS.get(str(buff_id))
            if item:
                category_str = item.category.value
        result.append((str(buff_id), str(name), bool(active), category_str, int(quantity or 1), bool(infinite)))
    return result


def _get_category_emoji(category: ItemCategory) -> str:
    if category == ItemCategory.CHEAP:
        return "🟢"
    elif category == ItemCategory.EXPENSIVE:
        return "🟡"
    elif category == ItemCategory.ULTRA:
        return "🔴"
    return "⚪"


def _build_shop_keyboard(selected_category: Optional[ItemCategory] = None, user_id: Optional[int] = None) -> InlineKeyboardBuilder:
    """
    Головний екран чорного ринку: «Придбати», опційно «Портал» (тільки якщо є прохід), «Назад».
    """
    b = InlineKeyboardBuilder()
    b.button(text="Придбати", callback_data="buffshop_items")
    if user_id is not None:
        try:
            from commands import vip as vip_mod

            if vip_mod.active_vip_tier(user_id) == "vip_plus":
                b.button(text="🛒 VIP Ринок (−25%)", callback_data="buffshop_vip_market")
        except Exception:
            pass
    b.button(text="Повернутися", callback_data="buff_shop")
    b.adjust(1)
    return b


def _build_confirm_keyboard(item_id: str, item: ItemDefinition) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    # Одна кнопка купівлі тільки за ліри
    b.button(text=f"Купити ({item.price} лір)", callback_data=f"buffshop_buy:{item_id}:krb")
    b.button(text="Повернутися", callback_data="buffshop_back")
    b.adjust(1)
    return b.as_markup()


def _get_item_button_text(item: ItemDefinition, is_active: bool) -> str:
    """Повертає текст кнопки для предмета згідно з вимогами"""
    if item.item_type == ItemType.ACTIVE:
        if not is_active:
            # Наголос на назві бафа, дія - в кінці
            return f"{item.name} - увімкнути"
        # Спеціальні тексти кнопок для активних предметів
        button_texts = {
            "cap": "Захист від голосу",
            "fire_extinguisher": "Скасувати дію",
            "signal_jammer": "Заглушити",
            "energy_drink": "Випити",
            "id_card": "Показати посвідчення",
            "flashlight": "Підсвітити гравця",
            "smoke_grenade": "Активувати дим",
            "underground_taxi": "Втекти",
            "super_dose": "Активувати",
            "time_stop": "Стоп",
            # Нові бафи чорного ринку
            "tommy_gun": "Tommy Gun - спрацювати",
            "knife": "Заточка - вдарити",
            "capone_hat": "Капелюх КаПоне - увімкнути",
            "flashlight_new": "Ліхтарик - показати вбивцю",
        }
        return button_texts.get(item.item_id, f"{item.name} - використати")
    else:
        # Для пасивних/авто - тільки активувати/деактивувати
        action_text = "Деактивувати" if is_active else "Активувати"
        return f"{action_text}: {item.name}"


def _build_owned_keyboard(owned: List[Tuple[str, str, bool, Optional[str], int, bool]], selected_category: Optional[ItemCategory] = None, user_id: Optional[int] = None) -> InlineKeyboardBuilder:
    """
    Клавіатура «Твої бафи» без жодних категорій.
    Просто список бафів з кнопками керування.
    Якщо user_id задано і є відсутні бафи порталу - додає кнопку «Отримати відсутні бафи порталу».
    """
    b = InlineKeyboardBuilder()

    # Кнопки тільки за назвами бафів: натискання перемикає /✖️ в тексті
    # Порядок фіксований, щоб збігався з текстом
    label_map = {
        "capone_hat": ("🎩", "Капелюх КаПоне"),
        "tommy_gun": ("🔫", "Tommy Gun"),
        "knife": ("🔪", "Заточка"),
        "flashlight_new": ("🔦", "Ліхтарик"),
        "black_opel": ("🚗", "Чорний «Опель»"),
        "parfum": ("🧴", "Парфум"),
        "black_cat": ("🐈‍⬛", "Чорний кіт"),
        "talisman": ("📿", "Талісман"),
        "fox_passport": ("📜", "Паспорт Лиса"),
        "wreath_lucky": ("💮", "Вінок «Щаслива ніч»"),
        "wreath_magic": ("🔮", "Вінок «Магія Купала»"),
    }

    # Створюємо мапу id -> is_active, щоб ставити /✖️ на кнопках
    status_map: Dict[str, bool] = {item_id: is_active for item_id, _name, is_active, _cat, _qty, _inf in owned}

    # Фіксований порядок, але показуємо тільки наявні бафи
    for item_id in ["capone_hat", "tommy_gun", "knife", "flashlight_new", "black_opel", "parfum", "black_cat", "talisman", "fox_passport", "wreath_lucky", "wreath_magic"]:
        if item_id not in status_map:
            continue
        emoji_symbol, label = label_map.get(item_id, ("", item_id))
        is_active = status_map.get(item_id, False)
        mark = "" if is_active else "✖️"
        icon_cid = custom_emoji_id_for_symbol(emoji_symbol) if emoji_symbol else None
        button_text = f"{mark} {label}".strip()
        kwargs = {
            "text": button_text,
            "callback_data": f"buffshop_toggle:{item_id}",
        }
        if icon_cid:
            kwargs["icon_custom_emoji_id"] = icon_cid
        elif emoji_symbol:
            kwargs["text"] = f"{mark} {emoji_symbol} {label}".strip()
        b.button(**kwargs)
        b.adjust(1)

    if user_id is not None:
        # Додаткові дії в межах «Мої бафи»
        search_cid = custom_emoji_id_for_symbol("🔍")
        coin_cid = custom_emoji_id_for_symbol("🪙")
        if search_cid:
            b.button(text="Обмінник", callback_data=f"profile_exchange:{user_id}", icon_custom_emoji_id=search_cid)
        else:
            b.button(text="🔍 Обмінник", callback_data=f"profile_exchange:{user_id}")
        if coin_cid:
            b.button(text="Продаж бафів", callback_data=f"profile_sell_buffs:{user_id}", icon_custom_emoji_id=coin_cid)
        else:
            b.button(text="🪙 Продаж бафів", callback_data=f"profile_sell_buffs:{user_id}")
        b.adjust(1)

    # Навігаційна кнопка: назад до профілю
    b.button(text="Повернутися", callback_data="buffshop_back_to_profile")
    b.adjust(1)
    return b


def _render_shop_text(balance: int, donate_balance: int, owned_buffs: List[Tuple[str, bool]], items_count: int, selected_category: Optional[ItemCategory] = None) -> str:
    lines = [
        "🛒 <b>ЧОРНИЙ РИНОК</b>",
        "",
        f"💰 Ліри: <b>{balance}</b>",
        f"🪙 Золоті монети: <b>{donate_balance}</b>",
        "",
        "<blockquote>Бафи — це предмети із підпілля Палермо, що дають ігрову перевагу.\n"
        "Тут купують не речі.\n"
        "Тут купують <b>вплив</b>.</blockquote>",
    ]
    return emoji_to_premium("\n".join(lines))


def _render_items_text(balance: int, donate_balance: int) -> str:
    """
    Окремий екран зі списком конкретних бафів та їх описами.
    """
    lines = [
        "🛒 <b>Чорний ринок - бафи</b>",
        "",
        f"💰Ліри: <b>{balance}</b>",
        "",
        "🔫 <b>Tommy Gun</b>",
        "Відбиває напад на вас - атакуючий гине замість цілі.",
        "",
        "🔪 <b>Заточка</b>",
        "Дозволяє вбити будь-якого гравця незалежно від ролі.",
        "",
        "🚗 <b>Чорний “Опель”</b>",
        "Дає можливість уникнути страти під час голосування.",
        "",
        "🎩 <b>Капелюх КаПоне</b>",
        "Робить вас недоступним для вбивства, перевірки та дій активних ролей на одну ніч.",
        "",
        "🔦 <b>Ліхтарик</b>",
        "Якщо вас вбили, наступного ранку показує, хто це зробив.",
        "",
        "🧴 <b>Парфум</b>",
        "Різкий запах відлякує Коханку.",
        "",
        "🐈‍⬛ <b>Чорний кіт</b>",
        "Може занюхати гравця з активним парфумом і таємно донести цю інформацію лише Коханці. Повністю захищає Коханку від усіх ефектів парфуму.",
        "",
        "📿 <b>Талісман</b>",
        "Кажуть, він береже від фатального пострілу. Один раз рятує вас від смерті.",
        "",
        "📜 <b>Паспорт Лиса</b>",
        "Фальшивий паспорт збиває зі сліду тих, хто надто цікавиться чужими справами. Якщо цієї ночі хтось спробує перевірити вашу роль - перевірка не спрацює.",
        "",
        "🌀 <b>Прохід у портал</b>",
        "Одноразовий прохід у Портал. Там - сюжет і унікальні бафи.",
    ]
    return emoji_to_premium("\n".join(lines))


def _render_items_text_short(balance: int) -> str:
    """Короткий варіант списку бафів (без довгих описів) - завжди під ліміт Telegram."""
    return emoji_to_premium(
        f"🛒 <b>Чорний ринок - бафи</b>\n\n"
        f"💰 Ліри: <b>{balance}</b>\n\n"
        "Оберіть предмет для покупки:"
    )


def _build_buff_shop_list_keyboard(pay_mode: str) -> InlineKeyboardMarkup:
    """
    Список товарів Чорного ринку (krb) або VIP Ринку (vip) з преміум-іконками на кнопках.
    Має збігатися з першим показом екрана - після покупки не втрачати icon_custom_emoji_id.
    """
    from commands import vip as vip_mod

    kb = InlineKeyboardBuilder()
    if pay_mode == "vip":
        fac = vip_mod.vip_buff_discount_factor("vip_plus")
        priced = [i for i in ITEMS.values() if i.price > 0 and not getattr(i, "shop_hidden", False)]
        for item in priced:
            vp = max(1, int(round(item.price * fac)))
            cid = custom_emoji_id_for_symbol(item.emoji)
            if cid:
                kb.button(
                    text=f"{item.name} - {vp}💰",
                    callback_data=f"buffshop_buy:{item.item_id}:vip",
                    icon_custom_emoji_id=cid,
                )
            else:
                kb.button(
                    text=f"{item.emoji} {item.name} - {vp}💰",
                    callback_data=f"buffshop_buy:{item.item_id}:vip",
                )
        if priced:
            kb.adjust(min(len(priced), 8))
    else:
        krb_items = [i for i in ITEMS.values() if not getattr(i, "shop_hidden", False)]
        for item in krb_items:
            cid = custom_emoji_id_for_symbol(item.emoji)
            if cid:
                kb.button(
                    text=f"{item.name} - {item.price}💰",
                    callback_data=f"buffshop_buy:{item.item_id}:krb",
                    icon_custom_emoji_id=cid,
                )
            else:
                kb.button(
                    text=f"{item.emoji} {item.name} - {item.price}💰",
                    callback_data=f"buffshop_buy:{item.item_id}:krb",
                )
        if krb_items:
            kb.adjust(min(len(krb_items), 8))
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    return kb.as_markup()


@router_buff_shop.callback_query(F.data == "buffshop_items")
async def buff_shop_items(callback: CallbackQuery, bot: Bot):
    """
    Екран зі списком усіх бафів та кнопками.
    Якщо натиснули в ЛС — редагуємо поточне повідомлення (зручна навігація без спаму).
    Якщо редагування неможливе — fallback на нове повідомлення в ЛС.
    """
    user_id = callback.from_user.id
    try:
        balance = _get_balance(user_id)
    except Exception:
        balance = 0
    balance = int(balance) if balance is not None else 0
    try:
        donate_balance = _get_donate_balance(user_id)
    except Exception:
        donate_balance = 0
    donate_balance = int(donate_balance) if donate_balance is not None else 0

    markup = _build_buff_shop_list_keyboard("krb")

    text = _render_items_text(balance, donate_balance)
    try:
        if _is_private_callback(callback):
            await callback.message.edit_text(
                text=text,
                reply_markup=markup,
                parse_mode="html",
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=markup,
                parse_mode="html",
            )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=markup,
                    parse_mode="html",
                )
            except Exception:
                pass
    except Exception:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"Чорний ринок - бафи. Ліри: {balance}. Оберіть предмет:",
                reply_markup=markup,
            )
        except Exception:
            pass
    try:
        await callback.answer()
    except Exception:
        pass


@router_buff_shop.callback_query(F.data == "buffshop_vip_market")
async def buff_shop_vip_market(callback: CallbackQuery, bot: Bot):
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return
    from commands import vip as vip_mod

    user_id = callback.from_user.id
    if vip_mod.active_vip_tier(user_id) != "vip_plus":
        await callback.answer("VIP Ринок лише з підпискою VIP+.", show_alert=True)
        return
    balance = _get_balance(user_id)
    text = emoji_to_premium(
        f"🛒 <b>VIP Ринок</b>\n\n"
        f"💰 Ліри: <b>{balance}</b>\n"
        "Інші ціни: дешевші бафи (−25%). Оберіть предмет:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=_build_buff_shop_list_keyboard("vip"), parse_mode="html")
    except TelegramBadRequest:
        await bot.send_message(
            user_id, text, reply_markup=_build_buff_shop_list_keyboard("vip"), parse_mode="html"
        )
    await callback.answer()


def _render_confirm_text(balance: int, donate_balance: int, item: ItemDefinition, items_count: int, has_ultra: bool) -> str:
    cat_emoji = _get_category_emoji(item.category)
    type_text = {
        ItemType.ACTIVE: "Активний (кнопка)",
        ItemType.PASSIVE: "Пасивний (автоматично)",
        ItemType.AUTO: "Авто (без вибору)"
    }.get(item.item_type, "Невідомо")
    price_line = f"{item.price} лір"
    lines = [
        "🛒 <b>Чорний ринок</b>",
        "",
        f"🥃 <b>Ліри:</b> <b>{balance}</b>",
        "",
        "Обрано предмет:",
        f"• {cat_emoji} {item.emoji} <b>{item.name}</b> - <b>{price_line}</b>",
        "",
        f"<b>Тип:</b> {type_text}",
        f"<b>Активація:</b> {item.activation_time.value}",
        "",
        "Підтвердити покупку?",
    ]
    return emoji_to_premium("\n".join(lines))


def _render_owned_text(balance: int, donate_balance: int, owned: List[Tuple[str, str, bool, Optional[str], int, bool]], selected_category: Optional[ItemCategory] = None) -> str:
    """
    Текст «Твої бафи» без категорій.
    Просто список бафів зі статусом, кількістю або знаком безкінечності (∞).
    """
    lines: List[str] = []
    lines.append(f"💰Ліри: {balance}")
    lines.append(f"🪙Золоті монети: {donate_balance}")
    lines.append("")
    lines.append("Твої бафи")
    lines.append("")

    if not owned:
        lines.append("Поки немає жодного бафа.")
        lines.append("Куплені бафи зʼявляться тут.")
        return emoji_to_premium("\n".join(lines))

    # Відображаємо в фіксованому порядку, щоб список був стабільний
    order = ["capone_hat", "tommy_gun", "knife", "flashlight_new", "black_opel", "parfum", "black_cat", "talisman", "fox_passport", "wreath_lucky", "wreath_magic"]
    owned_map = {item_id: (name, is_active, quantity, infinite) for item_id, name, is_active, _cat, quantity, infinite in owned}

    def line_for(item_id: str, label: str) -> str:
        name, _is_active, quantity, infinite = owned_map.get(item_id, (label, False, 0, False))
        if infinite:
            return f"{label} ∞"
        qty_suffix = f" (x{quantity})" if quantity and quantity > 1 else ""
        return f"{label}{qty_suffix}"

    if "capone_hat" in owned_map:
        lines.append(line_for("capone_hat", "🎩Капелюх КаПоне"))
    if "tommy_gun" in owned_map:
        lines.append(line_for("tommy_gun", "🔫Tommy Gun"))
    if "knife" in owned_map:
        lines.append(line_for("knife", "🔪Заточка"))
    if "flashlight_new" in owned_map:
        lines.append(line_for("flashlight_new", "🔦Ліхтарик"))
    if "black_opel" in owned_map:
        lines.append(line_for("black_opel", "🚗Чорний «Опель»"))
    if "parfum" in owned_map:
        lines.append(line_for("parfum", "🧴Парфум"))
    if "black_cat" in owned_map:
        lines.append(line_for("black_cat", "🐈‍⬛Чорний кіт"))
    if "talisman" in owned_map:
        lines.append(line_for("talisman", "📿Талісман"))
    if "fox_passport" in owned_map:
        lines.append(line_for("fox_passport", "📜Паспорт Лиса"))
    if "wreath_lucky" in owned_map:
        lines.append(line_for("wreath_lucky", "💮Вінок «Щаслива ніч»"))
    if "wreath_magic" in owned_map:
        lines.append(line_for("wreath_magic", "🔮Вінок «Магія Купала»"))

    lines.append("")
    return emoji_to_premium("\n".join(lines))


def _render_owned_unique_text(user_id: int, balance: int, donate_balance: int, owned: List[Tuple[str, str, bool, Optional[str], int, bool]]) -> str:
    """Текст екрану «Унікальні бафи порталу»: опис кожного бафа (що робить) + список наявних."""
    lines = ["🌀 <b>Унікальні бафи</b> 🌀", ""]
    status_map = {item_id: (name, is_active, quantity) for item_id, name, is_active, _cat, quantity, _inf in owned}
    has_any = False
    for uid in _unique_buff_profile_order():
        if uid not in status_map:
            continue
        has_any = True
        item = UNIQUE_BUFFS.get(uid)
        if not item:
            continue
        _, is_active, quantity = status_map[uid]
        qty = int(quantity or 1)
        suffix = f" (x{qty})" if qty > 1 else ""
        lines.append(f"{item.emoji} <b>{item.name}</b>{suffix}")
        if item.description:
            lines.append(f"<i>{item.description}</i>")
        lines.append("")
    if not has_any:
        lines.append("У тебе ще немає унікальних бафів. Пройди Портал, щоб отримати їх.")
    lines.append("")
    # emoji_to_premium лише в колбеках (buff_shop_owned_unique / toggle) - інакше подвійна
    # обгортка <tg-emoji> ламає розбір HTML у клієнті.
    return "\n".join(lines)


def _build_owned_unique_keyboard(owned: List[Tuple[str, str, bool, Optional[str], int, bool]], user_id: Optional[int] = None) -> InlineKeyboardBuilder:
    """Клавіатура екрану «Унікальні бафи»: перемикачі /✖️ для кожного унікального бафа."""
    b = InlineKeyboardBuilder()
    status_map = {item_id: is_active for item_id, _name, is_active, _cat, _qty, _inf in owned}
    for uid in _unique_buff_profile_order():
        if uid not in status_map:
            continue
        item = UNIQUE_BUFFS.get(uid)
        if not item:
            continue
        is_active = status_map.get(uid, False)
        mark = "" if is_active else "✖️"
        icon_cid = custom_emoji_id_for_symbol(item.emoji)
        if icon_cid:
            b.button(
                text=f"{mark} {item.name}".strip(),
                callback_data=f"buffshop_toggle_unique:{uid}",
                icon_custom_emoji_id=icon_cid,
            )
        else:
            b.button(text=f"{mark} {item.emoji} {item.name}", callback_data=f"buffshop_toggle_unique:{uid}")
        b.adjust(1)
    if user_id is not None:
        _, reward_granted = get_portal_progress(user_id)
        if reward_granted and _get_missing_portal_buff_ids(user_id):
            b.button(text="🎁 Отримати відсутні бафи порталу", callback_data="portal_grant_missing")
            b.adjust(1)
    b.button(text="Повернутися", callback_data="buffshop_owned")
    b.adjust(1)
    return b


async def _ensure_private(message: Message) -> bool:
    if message.chat.type != "private":
        await message.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.")
        return False
    return True


def _is_private_callback(callback: CallbackQuery) -> bool:
    return callback.message is not None and callback.message.chat.type == "private"


@router_buff_shop.message(Command("show_buff"))
async def show_buff_cmd(message: Message):
    """Команда /show_buff - показати «Мої бафи» в ЛС."""
    if not await _ensure_private(message):
        return
    await add_user_to_db(message)
    user_id = message.from_user.id
    balance = _get_balance(user_id)
    donate_balance = _get_donate_balance(user_id)
    owned = _get_user_buffs_detailed(user_id)
    await message.answer(
        emoji_to_premium(_render_owned_text(balance, donate_balance, owned, selected_category=None)),
        reply_markup=_build_owned_keyboard(owned, selected_category=None, user_id=user_id).as_markup(),
        parse_mode="html",
    )


@router_buff_shop.message(Command("buff_shop"))
async def buff_shop_open(message: Message):
    if not await _ensure_private(message):
        return
    await add_user_to_db(message)
    balance = _get_balance(message.from_user.id)
    donate_balance = _get_donate_balance(message.from_user.id)
    owned_buffs = _get_user_buffs(message.from_user.id)
    items_count = _get_user_items_count(message.from_user.id)
    await message.answer(
        _render_shop_text(balance, donate_balance, owned_buffs, items_count, selected_category=None),
        reply_markup=_build_shop_keyboard(selected_category=None, user_id=message.from_user.id).as_markup(),
        parse_mode="html"
    )


@router_buff_shop.callback_query(F.data == "buffshop_close")
async def buff_shop_close(callback: CallbackQuery):
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router_buff_shop.callback_query(F.data == "buffshop_back")
async def buff_shop_back(callback: CallbackQuery):
    """Повернення в головне меню ринку (з порталу, перемоги квесту тощо)."""
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return
    try:
        user_id = callback.from_user.id
        balance = _get_balance(user_id)
        donate_balance = _get_donate_balance(user_id)
        owned_buffs = _get_user_buffs(user_id)
        items_count = _get_user_items_count(user_id)
        text = _render_shop_text(balance, donate_balance, owned_buffs, items_count, selected_category=None)
        kb = _build_shop_keyboard(selected_category=None, user_id=user_id).as_markup()
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="html")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(text, reply_markup=kb, parse_mode="html")
    finally:
        try:
            await callback.answer()
        except Exception:
            pass


@router_buff_shop.callback_query(F.data.startswith("buffshop_category:"))
async def buff_shop_category(callback: CallbackQuery):
    """Обробка вибору категорії"""
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return
    
    category_str = (callback.data or "").split(":", 1)[1]
    category_map = {
        "cheap": ItemCategory.CHEAP,
        "expensive": ItemCategory.EXPENSIVE,
        "ultra": ItemCategory.ULTRA
    }
    selected_category = category_map.get(category_str)
    
    balance = _get_balance(callback.from_user.id)
    donate_balance = _get_donate_balance(callback.from_user.id)
    owned_buffs = _get_user_buffs(callback.from_user.id)
    items_count = _get_user_items_count(callback.from_user.id)
    try:
        await callback.message.edit_text(
            _render_shop_text(balance, donate_balance, owned_buffs, items_count, selected_category=selected_category),
            reply_markup=_build_shop_keyboard(selected_category=selected_category, user_id=callback.from_user.id).as_markup(),
            parse_mode="html"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()


@router_buff_shop.callback_query(F.data == "buffshop_owned")
async def buff_shop_owned(callback: CallbackQuery, bot: Bot):
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return

    user_id = callback.from_user.id
    try:
        balance = _get_balance(user_id)
        donate_balance = _get_donate_balance(user_id)
        owned = _get_user_buffs_detailed(user_id)
        await callback.message.edit_text(
            emoji_to_premium(_render_owned_text(balance, donate_balance, owned, selected_category=None)),
            reply_markup=_build_owned_keyboard(owned, selected_category=None, user_id=user_id).as_markup(),
            parse_mode="html"
        )
        await callback.answer()
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Повідомлення вже актуальне
            await callback.answer()
        else:
            # Інша помилка - надсилаємо нове повідомлення
            try:
                balance = _get_balance(user_id)
                donate_balance = _get_donate_balance(user_id)
                owned = _get_user_buffs_detailed(user_id)
                await bot.send_message(
                    chat_id=user_id,
                    text=emoji_to_premium(_render_owned_text(balance, donate_balance, owned, selected_category=None)),
                    reply_markup=_build_owned_keyboard(owned, selected_category=None, user_id=user_id).as_markup(),
                    parse_mode="html"
                )
                await callback.answer(" Відкрито нове повідомлення")
            except Exception as e2:
                await callback.answer(f"Помилка: {str(e2)}", show_alert=True)
    except Exception as e:
        # Якщо не вдалося відредагувати повідомлення, надсилаємо нове
        try:
            balance = _get_balance(user_id)
            donate_balance = _get_donate_balance(user_id)
            owned = _get_user_buffs_detailed(user_id)
            await bot.send_message(
                chat_id=user_id,
                text=emoji_to_premium(_render_owned_text(balance, donate_balance, owned, selected_category=None)),
                reply_markup=_build_owned_keyboard(owned, selected_category=None, user_id=user_id).as_markup(),
                parse_mode="html"
            )
            await callback.answer(" Відкрито нове повідомлення")
        except Exception as e2:
            await callback.answer(f"Помилка: {str(e2)}", show_alert=True)


@router_buff_shop.callback_query(F.data.startswith("buffshop_owned_category:"))
async def buff_shop_owned_category(callback: CallbackQuery, bot: Bot):
    """Обробка вибору категорії в розділі 'Твої бафи'"""
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return
    
    category_str = (callback.data or "").split(":", 1)[1]
    if category_str == "all":
        selected_category = None
    else:
        category_map = {
            "cheap": ItemCategory.CHEAP,
            "expensive": ItemCategory.EXPENSIVE,
            "ultra": ItemCategory.ULTRA
        }
        selected_category = category_map.get(category_str)
    
    user_id = callback.from_user.id
    try:
        balance = _get_balance(user_id)
        donate_balance = _get_donate_balance(user_id)
        owned = _get_user_buffs_detailed(user_id)
        await callback.message.edit_text(
            emoji_to_premium(_render_owned_text(balance, donate_balance, owned, selected_category=selected_category)),
            reply_markup=_build_owned_keyboard(owned, selected_category=selected_category, user_id=user_id).as_markup(),
            parse_mode="html"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await callback.answer(f"Помилка: {str(e)}", show_alert=True)
            return
    except Exception as e:
        await callback.answer(f"Помилка: {str(e)}", show_alert=True)
        return
    await callback.answer()


@router_buff_shop.callback_query(F.data == "buffshop_owned_unique")
async def buff_shop_owned_unique_cb(callback: CallbackQuery):
    """Екран «Унікальні бафи»: опис, звідки бафи, і перемикачі."""
    if not _is_private_callback(callback):
        await callback.answer("🛒 Доступ лише в ЛС.", show_alert=True)
        return
    user_id = callback.from_user.id
    balance = _get_balance(user_id)
    donate_balance = _get_donate_balance(user_id)
    owned = _get_user_buffs_detailed(user_id)
    text = emoji_to_premium(_render_owned_unique_text(user_id, balance, donate_balance, owned))
    kb = _build_owned_unique_keyboard(owned, user_id=user_id).as_markup()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="html")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb, parse_mode="html")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_grant_missing")
async def portal_grant_missing_cb(callback: CallbackQuery):
    """Видати відсутні портальні бафи (якщо портал пройдено, але не всі 6 були додані)."""
    if not _is_private_callback(callback):
        await callback.answer("Доступ лише в ЛС.", show_alert=True)
        return
    user_id = callback.from_user.id
    _, reward_granted = get_portal_progress(user_id)
    if not reward_granted:
        await callback.answer("Спочатку пройди портал до кінця.", show_alert=True)
        return
    missing = _get_missing_portal_buff_ids(user_id)
    if not missing:
        await callback.answer("У тебе вже всі 6 бафів порталу.", show_alert=True)
        return
    granted = 0
    for bid in missing:
        if grant_portal_reward(user_id, bid):
            granted += 1
    balance = _get_balance(user_id)
    donate_balance = _get_donate_balance(user_id)
    owned = _get_user_buffs_detailed(user_id)
    try:
        await callback.message.edit_text(
            emoji_to_premium(_render_owned_text(balance, donate_balance, owned, selected_category=None)),
            reply_markup=_build_owned_keyboard(owned, selected_category=None, user_id=user_id).as_markup(),
            parse_mode="html",
        )
    except TelegramBadRequest:
        pass
    await callback.answer(f"Додано відсутні бафи: {granted} шт. ", show_alert=True)


@router_buff_shop.callback_query(F.data.startswith("buffshop_toggle_unique:"))
async def buff_shop_toggle_unique_cb(callback: CallbackQuery):
    """Перемикання унікального бафа на екрані «Унікальні бафи»; оновлює той самий екран."""
    if not _is_private_callback(callback):
        await callback.answer("🛒 Доступ лише в ЛС.", show_alert=True)
        return
    user_id = callback.from_user.id
    buff_id = (callback.data or "").split(":", 1)[1]
    item = UNIQUE_BUFFS.get(buff_id)
    if not item:
        await callback.answer("Предмет не знайдено.", show_alert=True)
        return
    try:
        row = _db_fetchone_sync("""
            SELECT COALESCE(is_active, FALSE), COALESCE(quantity, 1)
            FROM user_buffs WHERE user_id = %s AND buff_id = %s FOR UPDATE
        """, (user_id, buff_id))
        if not row or int(row[1] or 0) <= 0:
            await callback.answer("Баф не знайдено або немає зарядів.", show_alert=True)
            return
        current, new_value = bool(row[0]), not bool(row[0])
        # Унікальні бафи можна вмикати всі; вимикаємо лише інші звичайні (ультра) бафи, не інші унікальні
        if new_value and item.category == ItemCategory.ULTRA:
            rows = _db_fetchall_sync("""
                SELECT buff_id FROM user_buffs
                WHERE user_id = %s AND COALESCE(is_active, FALSE) = TRUE
                AND buff_id != %s AND metadata->>'category' = %s
                AND COALESCE(is_unique, FALSE) = FALSE
            """, (user_id, buff_id, ItemCategory.ULTRA.value))
            for (active_id,) in rows or []:
                _db_execute_sync("UPDATE user_buffs SET is_active = FALSE WHERE user_id = %s AND buff_id = %s", (user_id, active_id))
        _db_execute_sync(
            "UPDATE user_buffs SET is_active = %s WHERE user_id = %s AND buff_id = %s",
            (new_value, user_id, buff_id),
        )
        _db_commit_sync()
        balance = _get_balance(user_id)
        donate_balance = _get_donate_balance(user_id)
        owned = _get_user_buffs_detailed(user_id)
        text = emoji_to_premium(_render_owned_unique_text(user_id, balance, donate_balance, owned))
        kb = _build_owned_unique_keyboard(owned, user_id=user_id).as_markup()
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="html")
        except TelegramBadRequest:
            pass
        await callback.answer(" Оновлено")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await callback.answer("Не вдалося оновити.", show_alert=True)


@router_buff_shop.callback_query(F.data.startswith("buffshop_toggle:"))
async def buff_shop_toggle(callback: CallbackQuery):
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return

    user_id = callback.from_user.id
    buff_id = (callback.data or "").split(":", 1)[1]
    
    # Отримуємо інформацію про предмет (магазин або унікальні портальні бафи)
    item = ITEMS.get(buff_id) or UNIQUE_BUFFS.get(buff_id)
    if not item:
        await callback.answer("Предмет не знайдено.", show_alert=True)
        return

    try:
        # toggle with row-level lock
        row = _db_fetchone_sync("""
            SELECT COALESCE(is_active, FALSE), metadata->>'category', COALESCE(quantity, 1)
            FROM user_buffs
            WHERE user_id = %s AND buff_id = %s
            FOR UPDATE
        """, (user_id, buff_id))
        if not row:
            await callback.answer("Баф не знайдено у твоєму списку.", show_alert=True)
            return
        if int(row[2] or 0) <= 0:
            await callback.answer("Немає зарядів. Купи ще один раз цей предмет.", show_alert=True)
            return

        current = bool(row[0])
        new_value = not current
        
        # Унікальні бафи можна вмикати всі одночасно; вимикаємо лише інші звичайні (ультра) бафи
        if new_value and item.category == ItemCategory.ULTRA:
            active_ultras = _db_fetchall_sync("""
                SELECT buff_id, buff_name FROM user_buffs
                WHERE user_id = %s 
                AND COALESCE(is_active, FALSE) = TRUE
                AND buff_id != %s
                AND metadata->>'category' = %s
                AND COALESCE(is_unique, FALSE) = FALSE
            """, (user_id, buff_id, ItemCategory.ULTRA.value))
            
            if active_ultras:
                # Деактивуємо тільки звичайні ультра-бафи (унікальні залишаються ввімкненими)
                for active_buff_id, active_name in active_ultras:
                    _db_execute_sync("""
                        UPDATE user_buffs
                        SET is_active = FALSE
                        WHERE user_id = %s AND buff_id = %s
                    """, (user_id, active_buff_id))
                
                # Формуємо повідомлення про деактивацію
                if len(active_ultras) == 1:
                    active_name = active_ultras[0][1]
                    await callback.answer(
                        f"ℹ️ Деактивовано інший ультра-баф: {active_name}\n"
                        f"Активовано: {item.name}",
                        show_alert=True
                    )
                else:
                    await callback.answer(
                        f"ℹ️ Деактивовано {len(active_ultras)} інших ультра-бафів\n"
                        f"Активовано: {item.name}",
                        show_alert=True
                    )
        
        _db_execute_sync("""
            UPDATE user_buffs
            SET is_active = %s
            WHERE user_id = %s AND buff_id = %s
        """, (new_value, user_id, buff_id))
        _db_commit_sync()

        balance = _get_balance(user_id)
        donate_balance = _get_donate_balance(user_id)
        owned = _get_user_buffs_detailed(user_id)
        try:
            await callback.message.edit_text(
                emoji_to_premium(_render_owned_text(balance, donate_balance, owned, selected_category=None)),
                reply_markup=_build_owned_keyboard(owned, selected_category=None, user_id=user_id).as_markup(),
                parse_mode="html"
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        await callback.answer(" Оновлено")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await callback.answer("Не вдалося оновити баф. Спробуй ще раз.", show_alert=True)


@router_buff_shop.callback_query(F.data.startswith("buffshop_pick:"))
async def buff_shop_pick(callback: CallbackQuery):
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return

    item_id = (callback.data or "").split(":", 1)[1]
    item = ITEMS.get(item_id)
    if not item:
        await callback.answer("Предмет не знайдено.", show_alert=True)
        return

    user_id = callback.from_user.id
    balance = _get_balance(user_id)
    donate_balance = _get_donate_balance(user_id)
    items_count = _get_user_items_count(user_id)
    has_ultra = any(
        cat == ItemCategory.ULTRA.value 
        for _, _, _, cat, _, _ in _get_user_buffs_detailed(user_id)
        if cat
    )
    
    try:
        await callback.message.edit_text(
            _render_confirm_text(balance, donate_balance, item, items_count, has_ultra),
            reply_markup=_build_confirm_keyboard(item_id, item),
            parse_mode="html"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()


@router_buff_shop.callback_query(F.data.startswith("buffshop_buy:"))
async def buff_shop_buy(callback: CallbackQuery, bot: Bot):
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return

    user_id = callback.from_user.id
    parts = (callback.data or "").split(":")
    item_id = parts[1] if len(parts) >= 2 else ""
    pay_mode = parts[2] if len(parts) >= 3 else "krb"
    item = ITEMS.get(item_id)
    if not item:
        await callback.answer("Предмет не знайдено.", show_alert=True)
        return

    from commands import vip as vip_mod

    if pay_mode == "vip":
        if vip_mod.active_vip_tier(user_id) != "vip_plus":
            await callback.answer("VIP Ринок лише для VIP+.", show_alert=True)
            return
        pay_price = max(1, int(round(item.price * vip_mod.vip_buff_discount_factor("vip_plus"))))
    else:
        pay_price = int(item.price)

    try:
        row = _db_fetchone_sync(
            "SELECT COALESCE(balance, 0), COALESCE(donate_coins, 0) FROM users WHERE id = %s FOR UPDATE",
            (user_id,),
        )
        if row is None:
            _db_execute_sync(
                "INSERT INTO users (id, tg_name, link, balance, donate_coins) VALUES (%s, %s, %s, 0, 0) ON CONFLICT (id) DO NOTHING",
                (user_id, callback.from_user.first_name, callback.from_user.username),
            )
            _db_commit_sync()
            row = _db_fetchone_sync(
                "SELECT COALESCE(balance, 0), COALESCE(donate_coins, 0) FROM users WHERE id = %s FOR UPDATE",
                (user_id,),
            )
        balance = int(row[0]) if row else 0
        donate_balance = int(row[1]) if row and len(row) > 1 else 0

        if balance < pay_price:
            await callback.answer("Недостатньо лір.", show_alert=True)
            if pay_mode == "vip":
                low_text = emoji_to_premium(
                    f"🛒 <b>VIP Ринок</b>\n\n💰 Ліри: <b>{balance}</b>\nОберіть предмет:"
                )
            else:
                low_text = _render_items_text(balance, donate_balance)
            try:
                await callback.message.edit_text(
                    low_text,
                    reply_markup=_build_buff_shop_list_keyboard(pay_mode),
                    parse_mode="html",
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
            return
        _db_execute_sync(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s",
            (pay_price, user_id),
        )
        amount_paid, pay_currency = pay_price, "KRB"

        import json
        if item.item_id == "portal_pass":
            grant_portal_access(user_id)
            _db_execute_sync("""
                INSERT INTO buff_purchases (user_id, buff_id, buff_name, amount_paid, currency)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, item.item_id, item.name, amount_paid, pay_currency))
            _db_commit_sync()
            await callback.answer(" Прохід у портал отримано! Тепер у головному меню ринку зʼявиться кнопка «Портал».", show_alert=True)
            # Повертаємо до списку предметів
            try:
                await callback.message.edit_text(
                    _render_items_text(_get_balance(user_id), _get_donate_balance(user_id)),
                    reply_markup=_build_buff_shop_list_keyboard("krb"),
                    parse_mode="html",
                )
            except Exception:
                pass
            return
        else:
            metadata = {
                "category": item.category.value,
                "item_type": item.item_type.value,
                "activation_time": item.activation_time.value,
                "cooldown": item.cooldown.value,
                "priority": item.priority,
            }
            if item.effect_data:
                metadata["effect_data"] = item.effect_data
            _db_execute_sync("""
                INSERT INTO user_buffs (user_id, buff_id, buff_name, is_active, metadata, quantity)
                VALUES (%s, %s, %s, FALSE, %s::jsonb, 1)
                ON CONFLICT (user_id, buff_id) DO UPDATE
                  SET buff_name = EXCLUDED.buff_name, metadata = EXCLUDED.metadata,
                      quantity = user_buffs.quantity + 1
            """, (user_id, item.item_id, item.name, json.dumps(metadata)))
            _db_execute_sync("""
                INSERT INTO buff_purchases (user_id, buff_id, buff_name, amount_paid, currency)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, item.item_id, item.name, amount_paid, pay_currency))
            _db_commit_sync()

        new_balance = _get_balance(user_id)
        new_donate = _get_donate_balance(user_id)
        try:
            if pay_mode == "vip":
                list_text = emoji_to_premium(
                    f"🛒 <b>VIP Ринок</b>\n\n💰 Ліри: <b>{new_balance}</b>\nОберіть предмет:"
                )
            else:
                list_text = _render_items_text(new_balance, new_donate)
            await callback.message.edit_text(
                list_text,
                reply_markup=_build_buff_shop_list_keyboard(pay_mode),
                parse_mode="html",
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        await callback.answer(f" Куплено: {item.emoji} {item.name}", show_alert=True)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        await callback.answer("Помилка покупки. Спробуй ще раз.", show_alert=True)


@router_buff_shop.callback_query(F.data.startswith("buffshop_use:"))
async def buff_shop_use(callback: CallbackQuery, bot: Bot):
    """Використання активного предмета"""
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в особистих повідомленнях бота.", show_alert=True)
        return
    
    user_id = callback.from_user.id
    item_id = (callback.data or "").split(":", 1)[1]
    item = ITEMS.get(item_id) or UNIQUE_BUFFS.get(item_id)
    
    if not item:
        await callback.answer("Предмет не знайдено.", show_alert=True)
        return
    
    if item.item_type != ItemType.ACTIVE:
        await callback.answer("Цей предмет не можна використати вручну.", show_alert=True)
        return
    
    # TODO: Інтеграція з ігровим процесом - викликати активацію предмета
    # Поки що просто повідомлення
    await callback.answer(f"💉 {item.name} активовано! (інтеграція з грою - в розробці)", show_alert=True)


def _is_bot_owner(user_id: int) -> bool:
    """Перевіряє, чи користувач є власником бота"""
    if user_id == BOT_OWNER_ID:
        return True
    
    # Перевіряємо чи є в таблиці founders
    try:
        row = _db_fetchone_sync("SELECT founder_id FROM founders WHERE founder_id = %s AND is_active = TRUE", (user_id,))
        if row:
            return True
    except Exception:
        pass
    
    return False


@router_buff_shop.message(Command("clear_all_buffs"))
async def clear_all_buffs_command(message: Message):
    """Команда для видалення всіх бафів у всіх гравців (тільки для власника)"""
    user_id = message.from_user.id
    
    # Перевірка прав доступу
    if not _is_bot_owner(user_id):
        await message.answer(
            "<b>Доступ заборонено</b>\n\n"
            "Ця команда доступна тільки для власника бота.",
            parse_mode="html"
        )
        return
    
    # Перевіряємо чи є підтвердження в тексті команди
    command_text = message.text or ""
    if "confirm" not in command_text.lower():
        # Показуємо попередження та кнопку підтвердження
        total_row = _db_fetchone_sync("SELECT COUNT(*) FROM user_buffs")
        total_buffs = total_row[0] if total_row else 0
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text=" Так, видалити всі бафи",
            callback_data="clear_buffs_confirm"
        ))
        builder.add(InlineKeyboardButton(
            text="Скасувати",
            callback_data="clear_buffs_cancel"
        ))
        
        await message.answer(
            f"⚠️ <b>Увага!</b>\n\n"
            f"Ви збираєтеся видалити <b>всі бафи</b> у всіх гравців!\n\n"
            f"📊 Зараз у базі: <b>{total_buffs}</b> записів бафів\n\n"
            f"Цю дію неможливо скасувати!\n\n"
            f"Для підтвердження натисніть кнопку нижче або використайте:\n"
            f"<code>/clear_all_buffs confirm</code>",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        return
    
    try:
        # Видаляємо всі бафи
        deleted_count = _db_execute_sync("DELETE FROM user_buffs")
        _db_commit_sync()
        
        await message.answer(
            f" <b>Всі бафи видалено</b>\n\n"
            f"Видалено записів: <b>{deleted_count}</b>\n\n"
            f"Всі бафи у всіх гравців були видалені з бази даних.",
            parse_mode="html"
        )
        
        print(f"🔧 [ADMIN] Користувач {user_id} видалив всі бафи. Видалено записів: {deleted_count}")
        
    except Exception as e:
        await message.answer(
            f"<b>Помилка</b>\n\n"
            f"Не вдалося видалити бафи:\n<code>{str(e)}</code>",
            parse_mode="html"
        )
        print(f"Помилка видалення бафів: {e}")


@router_buff_shop.callback_query(F.data == "clear_buffs_confirm")
async def clear_buffs_confirm_callback(callback: CallbackQuery):
    """Підтвердження видалення всіх бафів"""
    user_id = callback.from_user.id
    
    if not _is_bot_owner(user_id):
        await callback.answer("Доступ заборонено", show_alert=True)
        return
    
    try:
        # Видаляємо всі бафи
        deleted_count = _db_execute_sync("DELETE FROM user_buffs")
        _db_commit_sync()
        
        await callback.message.edit_text(
            f" <b>Всі бафи видалено</b>\n\n"
            f"Видалено записів: <b>{deleted_count}</b>\n\n"
            f"Всі бафи у всіх гравців були видалені з бази даних.",
            parse_mode="html"
        )
        
        await callback.answer(" Всі бафи видалено", show_alert=True)
        print(f"🔧 [ADMIN] Користувач {user_id} видалив всі бафи. Видалено записів: {deleted_count}")
        
    except Exception as e:
        await callback.answer(f"Помилка: {str(e)}", show_alert=True)
        print(f"Помилка видалення бафів: {e}")


@router_buff_shop.callback_query(F.data == "clear_buffs_cancel")
async def clear_buffs_cancel_callback(callback: CallbackQuery):
    """Скасування видалення бафів"""
    user_id = callback.from_user.id
    
    if not _is_bot_owner(user_id):
        await callback.answer("Доступ заборонено", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<b>Операцію скасовано</b>\n\n"
        "Всі бафи залишилися без змін.",
        parse_mode="html"
    )
    await callback.answer("Операцію скасовано")


@router_buff_shop.message(Command("clear_user_buffs"))
async def clear_user_buffs_command(message: Message):
    """Команда для видалення бафів конкретного користувача (тільки для власника)
    
    Використання: /clear_user_buffs <user_id>
    Приклад: /clear_user_buffs 123456789
    """
    user_id = message.from_user.id
    
    # Перевірка прав доступу
    if not _is_bot_owner(user_id):
        await message.answer(
            "<b>Доступ заборонено</b>\n\n"
            "Ця команда доступна тільки для власника бота.",
            parse_mode="html"
        )
        return
    
    # Отримуємо user_id з команди
    command_parts = (message.text or "").split()
    if len(command_parts) < 2:
        await message.answer(
            "<b>Невірний формат</b>\n\n"
            "Використання: <code>/clear_user_buffs &lt;user_id&gt;</code>\n\n"
            "Приклад: <code>/clear_user_buffs 123456789</code>",
            parse_mode="html"
        )
        return
    
    try:
        target_user_id = int(command_parts[1])
    except ValueError:
        await message.answer(
            "<b>Невірний user_id</b>\n\n"
            "user_id має бути числом.\n\n"
            "Приклад: <code>/clear_user_buffs 123456789</code>",
            parse_mode="html"
        )
        return
    
    try:
        # Перевіряємо чи є користувач
        user_result = _db_fetchone_sync("SELECT tg_name FROM users WHERE id = %s", (target_user_id,))
        user_name = user_result[0] if user_result else f"ID: {target_user_id}"
        
        # Перевіряємо скільки бафів у користувача
        count_row = _db_fetchone_sync("SELECT COUNT(*) FROM user_buffs WHERE user_id = %s", (target_user_id,))
        buffs_count = count_row[0] if count_row else 0
        
        if buffs_count == 0:
            await message.answer(
                f"ℹ️ <b>Немає бафів</b>\n\n"
                f"У користувача <b>{user_name}</b> (ID: {target_user_id}) немає бафів.",
                parse_mode="html"
            )
            return
        
        # Видаляємо бафи користувача
        deleted_count = _db_execute_sync("DELETE FROM user_buffs WHERE user_id = %s", (target_user_id,))
        _db_commit_sync()
        
        await message.answer(
            f" <b>Бафи видалено</b>\n\n"
            f"Користувач: <b>{user_name}</b> (ID: {target_user_id})\n"
            f"Видалено записів: <b>{deleted_count}</b>",
            parse_mode="html"
        )
        
        print(f"🔧 [ADMIN] Користувач {user_id} видалив бафи у {target_user_id} ({user_name}). Видалено: {deleted_count}")
        
    except Exception as e:
        await message.answer(
            f"<b>Помилка</b>\n\n"
            f"Не вдалося видалити бафи:\n<code>{str(e)}</code>",
            parse_mode="html"
        )
        print(f"Помилка видалення бафів користувача: {e}")

def _build_subscription_shop(uid: int, mode: str) -> tuple[str, InlineKeyboardMarkup]:
    """
    Текст і клавіатура магазину підписок.
    mode: all | vip | chat
    """
    from commands.buy import (
        ShopManager,
        VIP_GAME_SUBSCRIPTION_IDS,
        CHAT_SUBSCRIPTION_IDS,
        _catalog_block_store_html,
    )
    from commands import vip as vip_mod
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    sm = ShopManager.SHOP_ITEMS
    builder = InlineKeyboardBuilder()

    def _add_buy_buttons(ids: tuple[str, ...]) -> None:
        for iid in ids:
            if iid not in sm:
                continue
            item = sm[iid]
            star_p = vip_mod.effective_star_price(item, uid)
            builder.button(
                text=f"{item.name} - {star_p} ⭐",
                callback_data=f"buy_{iid}",
            )

    if mode in ("all", "vip"):
        _add_buy_buttons(VIP_GAME_SUBSCRIPTION_IDS)
    if mode in ("all", "chat"):
        _add_buy_buttons(CHAT_SUBSCRIPTION_IDS)

    builder.button(text="Повернутися", callback_data="buff_shop")
    builder.adjust(1)

    if mode == "all":
        shop_text = (
            "💎 <b>Магазин підписок</b> 💎\n\n"
            "⭐ Оберіть тариф і натисніть кнопку нижче.\n\n"
            "🎮 <b>VIP</b>\n"
            "<i>Рулетка, бонуси, страховка, VIP Ринок (VIP+), значок.</i>\n\n"
        )
        for iid in VIP_GAME_SUBSCRIPTION_IDS:
            if iid in sm:
                shop_text += _catalog_block_store_html(sm[iid], uid, vip_mod)
        shop_text += "\n💬 <b>Підписка</b>\n"
        shop_text += "<i>Статус у групі на 1-12 місяців.</i>\n\n"
        for iid in CHAT_SUBSCRIPTION_IDS:
            if iid in sm:
                shop_text += _catalog_block_store_html(sm[iid], uid, vip_mod)
    elif mode == "vip":
        shop_text = (
            "🎮 <b>VIP</b>\n\n"
            "<i>Рулетка, щоденні гроші, страховка, VIP Ринок (для VIP+), значок біля ніку.</i>\n\n"
            "⭐ Оберіть тариф:\n\n"
        )
        for iid in VIP_GAME_SUBSCRIPTION_IDS:
            if iid in sm:
                shop_text += _catalog_block_store_html(sm[iid], uid, vip_mod)
    else:
        shop_text = (
            "💬 <b>Підписка</b>\n\n"
            "<i>Статус і підтримка в групі на обраний термін (1-12 місяців).</i>\n\n"
            "⭐ Оберіть тариф:\n\n"
        )
        for iid in CHAT_SUBSCRIPTION_IDS:
            if iid in sm:
                shop_text += _catalog_block_store_html(sm[iid], uid, vip_mod)

    return shop_text, builder.as_markup()


async def _reply_subscription_shop(callback: CallbackQuery, mode: str) -> None:
    from premium_emoji import emoji_to_premium

    uid = callback.from_user.id if callback.from_user else 0
    shop_text, markup = _build_subscription_shop(uid, mode)
    try:
        await callback.message.edit_text(
            emoji_to_premium(shop_text, skip_vip_badges=True),
            reply_markup=markup,
            parse_mode="html",
        )
    except Exception:
        await callback.message.answer(
            emoji_to_premium(shop_text, skip_vip_badges=True),
            reply_markup=markup,
            parse_mode="html",
        )
    await callback.answer()


@router_buff_shop.callback_query(F.data == "shop_subscriptions")
async def shop_subscriptions_callback(callback: CallbackQuery):
    """Повний каталог підписок (VIP + чат) - для зворотної сумісності."""
    await _reply_subscription_shop(callback, "all")


@router_buff_shop.callback_query(F.data == "shop_subscriptions_vip")
async def shop_subscriptions_vip_callback(callback: CallbackQuery):
    await _reply_subscription_shop(callback, "vip")


@router_buff_shop.callback_query(F.data == "shop_subscriptions_chat")
async def shop_subscriptions_chat_callback(callback: CallbackQuery):
    await _reply_subscription_shop(callback, "chat")


@router_buff_shop.callback_query(F.data == "buff_shop_menu")
async def buff_shop_menu_callback(callback: CallbackQuery):
    """Перекидання у магазин бафів"""
    balance = _get_balance(callback.from_user.id)
    donate_balance = _get_donate_balance(callback.from_user.id)
    owned_buffs = _get_user_buffs(callback.from_user.id)
    items_count = _get_user_items_count(callback.from_user.id)
    
    try:
        await callback.message.edit_text(
            _render_shop_text(balance, donate_balance, owned_buffs, items_count, selected_category=None),
            reply_markup=_build_shop_keyboard(selected_category=None, user_id=callback.from_user.id).as_markup(),
            parse_mode="html"
        )
    except Exception:
        await callback.message.answer(
            _render_shop_text(balance, donate_balance, owned_buffs, items_count, selected_category=None),
            reply_markup=_build_shop_keyboard(selected_category=None, user_id=callback.from_user.id).as_markup(),
            parse_mode="html"
        )
    
    await callback.answer()


@router_buff_shop.callback_query(F.data == "buff_shop")
async def buff_shop_back_callback(callback: CallbackQuery):
    """
    Повернення з чорного ринку до крамниці (Профіль → Крамниця → Бафи).
    """
    if not _is_private_callback(callback):
        await callback.answer("🛒 Магазин доступний лише в ЛС.", show_alert=True)
        return
    try:
        from commands.start import shop_main_cb
        await shop_main_cb(callback)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            # Не вдалося редагувати (напр. повідомлення з відео) - надсилаємо нове з меню крамниці
            from commands.start import _shop_main_text_and_keyboard

            shop_text, shop_kb = _shop_main_text_and_keyboard()
            await callback.message.answer(shop_text, reply_markup=shop_kb, parse_mode="html")
        await callback.answer()
    except Exception:
        await callback.answer()

@router_buff_shop.message(Command("clear_buffs_stats"))
async def clear_buffs_stats_command(message: Message):
    """Команда для перегляду статистики бафів (тільки для власника)"""
    user_id = message.from_user.id
    
    # Перевірка прав доступу
    if not _is_bot_owner(user_id):
        await message.answer(
            "<b>Доступ заборонено</b>\n\n"
            "Ця команда доступна тільки для власника бота.",
            parse_mode="html"
        )
        return
    
    try:
        # Статистика по бафам
        stats = _db_fetchall_sync("""
            SELECT 
                buff_id,
                COUNT(*) as total_count,
                SUM(CASE WHEN COALESCE(is_active, FALSE) = TRUE THEN 1 ELSE 0 END) as active_count,
                SUM(COALESCE(quantity, 1)) as total_quantity
            FROM user_buffs
            GROUP BY buff_id
            ORDER BY total_count DESC
        """)
        
        if not stats:
            await message.answer(
                "📊 <b>Статистика бафів</b>\n\n"
                "Бафи не знайдено.",
                parse_mode="html"
            )
            return
        
        # Загальна статистика
        unique_users_row = _db_fetchone_sync("SELECT COUNT(DISTINCT user_id) FROM user_buffs")
        unique_users = unique_users_row[0] if unique_users_row else 0
        
        total_buffs_row = _db_fetchone_sync("SELECT COUNT(*) FROM user_buffs")
        total_buffs = total_buffs_row[0] if total_buffs_row else 0
        
        stats_text = f"📊 <b>Статистика бафів</b>\n\n"
        stats_text += f"👥 Унікальних гравців з бафами: <b>{unique_users}</b>\n"
        stats_text += f"📦 Всього бафів: <b>{total_buffs}</b>\n\n"
        stats_text += "<b>По типах бафів:</b>\n"
        
        for buff_id, total_count, active_count, total_quantity in stats[:20]:  # Перші 20
            item = ITEMS.get(buff_id) or UNIQUE_BUFFS.get(buff_id)
            item_name = item.name if item else buff_id
            stats_text += f"• {item_name}: {total_count} записів ({active_count} активних, {total_quantity} зарядів)\n"
        
        if len(stats) > 20:
            stats_text += f"\n... та ще {len(stats) - 20} типів бафів"
        
        await message.answer(stats_text, parse_mode="html")
        
    except Exception as e:
        await message.answer(
            f"<b>Помилка</b>\n\n"
            f"Не вдалося отримати статистику:\n<code>{str(e)}</code>",
            parse_mode="html"
        )
        print(f"Помилка отримання статистики бафів: {e}")


# =============================================================================
# ПОРТАЛ: вхід, сюжет, відео по сценах, нагорода - унікальні бафи
# =============================================================================

# Ціна за «квиток» у сюжеті порталу (списується в першій сцені)
PORTAL_ENTRY_PRICE_CARB = 300

# Шляхи до відео по сценах порталу (Media/1 Сцена.mp4 … Media/9 сцена.mp4)
PORTAL_VIDEOS: Dict[str, str] = {
    "start": "Media/1 Сцена.mp4",      # 1 - пророк, купити портал
    "station": "Media/2 сцена.mp4",   # 2 - вокзал, мужик Польща
    "scene_3": "Media/3 сцена.mp4",   # 3 - мужик злий / площа
    "scene_4": "Media/4 сцена.mp4",   # 4 - парфуми / Хрещатик
    "scene_5": "Media/5 сцена.mp4",   # 5 - стрічка / таксі
    "scene_6": "Media/6 сцена.mp4",   # 6 - бабуся насіння / перевірка
    "scene_7": "Media/7 сцена.mp4",   # 7 - Київ / музикант
    "scene_8": "Media/8 сцена.mp4",   # 8 - музикант / Макдак
    "scene_9": "Media/9 сцена.mp4",   # 9 - Макдак / перемога
}

PORTAL_STORY_START = (
    "Хочеш побачити майбутнє, пане? За 300 лір - портал на 100 років вперед. "
    "Один раз натиснеш - і ти вже не в 1937-му. Але назад повернешся тільки якщо сам захочеш… чи ні."
)

PORTAL_REFUSE_TEXT = (
    "Ну і сиди в своєму 1937-му з мафією і без інтернету, мудило."
)

# Сцена: Центральний вокзал, мужик з автобусом у Польщу
PORTAL_STATION = (
    "Ти вивалюєшся з синьо-жовтої іскри прямо на колію біля Центрального вокзалу. "
    "Пахне соляркою, шаурмою і свободою. Над головою - величезний LED-екран з рекламою "
    "«Приват24 - твій гаманець у смартфоні». До тебе підходить мужик у спортивному костюмі Адідас і китайських кросівках.\n\n"
    " -  Бери автобус в Пшеку, братишка! 800 грн, місце біля вікна, Wi-Fi, розетка. "
    "Через 18 годин уже в Кракові, пивко, дівки, робота на будові. Що скажеш?"
)

# Вибір «Го в Польщу» - повернення в 1937, усі знають що здався. Кінець, без нагороди.
PORTAL_POLAND_YES_END = (
    "Мужик радісно клацає пальцями. Ти чуєш знайомий звук порталу. Тебе засмоктує назад у 1937-й.\n\n"
    "«Ти повернувся додому. Але чомусь усі вже знають, що ти здався полякам…»"
)

# Вибір «Нах@й твою Польщу» - мужик злий
PORTAL_ANGRY = (
    "Мужик червоніє, очі наливаються кров'ю:\n"
    " -  Ти шо, сепар? Бери автобус, кажу, або пиздець тобі!"
)

# Після «ВТЄКТИ» - Вокзальна площа, мужик з парфумами
PORTAL_SQUARE = (
    "Ти вибігаєш з вокзалу на Вокзальну площу. Серце калатає. До тебе одразу підходить другий мужик, "
    "цього разу в старій шкірянці, з пакетом «парфуми Gucci, Dior, Chanel - по 150 грн, оригінал з Туреччини, нюхай, не підведу»."
)
PORTAL_PERFUME_PRICE_CARB = 150

# Купити парфуми - платиш, «тепер ти пахнеш як справжній киянин», далі Хрещатик
PORTAL_PERFUME_BUY_SUCCESS = (
    "Ти платиш. Мужик задоволено: «Тепер ти пахнеш як справжній киянин 2021 року. Іди, братишка, вперед!»"
)

# Після парфумів - Хрещатик, дівчата з стрічками
PORTAL_KRESHCHATIK = (
    "Йдеш Хрещатиком (ну майже). Тебе оточують три дівчини в яскравих футболках і з навушниками. В руках - кольорові стрічки.\n\n"
    " -  Бери стрічку, бро! 100 грн - і ти в тренді, як справжній киянин 2021-го. Без неї далі не пустимо, бо «не наш вайб»."
)
PORTAL_RIBBON_PRICE_CARB = 100

# Купити стрічку - пов'язують, «Макдак два квартали прямо», далі таксі
PORTAL_RIBBON_BUY_SUCCESS = (
    "Тобі пов'язують стрічку на руку. Одна з дівчат:\n"
    " -  Макдак на Хрещатику, два квартали прямо. Біжи, легендо."
)

# Після стрічки - Lacetti, таксі до Макдака
PORTAL_TAXI = (
    "До тебе під'їжджає старенька Lacetti з наклейкою «Таксі - дешево, швидко».\n\n"
    " -  Бери, братан! До Макдака - 70 грн, по лічильнику не поїдемо, бо він «сломався». "
    "Або 100 грн і я тобі анекдот про політиків розкажу. Що береш?"
)
PORTAL_TAXI_PRICE_CARB = 70

# Сісти в таксі - об'їзд, викидає, портал назад. Кінець гри, без нагороди.
PORTAL_TAXI_YES_END = (
    "Ти сідаєш. Він завертає не туди. «Беру ще 200 грн за об'їзд», або вилазь. "
    "Відмовляєшся - викидає посеред вулиці. Портал. Назад у 1937-й."
)

# Пішки піду - водій кричить, ти вже далеко, далі бабуся з насінням
PORTAL_TAXI_NO_SUCCESS = (
    "Ти йдеш пішки. Водій кричить услід: «Скряга!» Але ти вже далеко."
)

# Біля переходу - бабуся з насінням
PORTAL_GRANDMA = (
    "Біля переходу бабуся з сумкою.\n\n"
    " -  Синку, бери насіннячко! Смажене, солоне, з часником - 50 грн стаканчик. "
    "Без нього далі не пустимо - то наш київський вайб."
)
PORTAL_SEEDS_PRICE_CARB = 50

# Купити насіння - стаканчик, «Макдак близько», далі перевірка
PORTAL_SEEDS_BUY_SUCCESS = (
    "Береш стаканчик. Бабуся: «Молодець. Іди, Макдак близько. Не розсип.»"
)

# Після насіння - хлопці з раціями, перевірка
PORTAL_CHECK = (
    "Тебе зупиняють двоє хлопців у балаклавах і спортивках, з раціями.\n\n"
    " -  Добрий день! Перевірка. Покажи стрічку, понюхай парфуми… А тепер скажи швидко: "
    "«Київ - найкраще місто!» Якщо правильно - пропустимо. Якщо ні - будеш пояснювати, хто ти такий."
)

# Сказати «Київ - найкраще місто!» - пропускають, далі нагорода
PORTAL_KYIV_YES_SUCCESS = (
    "Ти кажеш голосно. Вони кивають:\n"
    " -  Нормально, проходь. Макдак прямо."
)

# Я з 1937, Палермо крутіше - провокація, портал назад. Кінець гри, без нагороди.
PORTAL_KYIV_REFUSE_END = (
    "Хлопці: «Це шо, провокація?» Тебе фотографують, постять у групу «Підозрілі типи». Портал засмоктує. Назад у 30-ті."
)

# Після «Київ - найкраще місто!» - музикант біля переходу
PORTAL_MUSICIAN = (
    "Біля підземного переходу чувак грає щось попсове на гітарі.\n\n"
    " -  Бери QR, скинь 50 грн на каву музиканту - і я зіграю тобі персонально «Океан Ельзи» або що захочеш. "
    "Без донату - не пущу, енергія не та."
)
PORTAL_MUSICIAN_PRICE_CARB = 50

# Скинути 50 і послухати - грає приспів, «Макдак чекає», далі Макдак
PORTAL_MUSICIAN_BUY_SUCCESS = (
    "Ти скидаєш. Він грає приспів. Мурашки.\n"
    " -  Іди, Макдак чекає."
)

# Макдак - касирка, акція для «туристів з минулого»
PORTAL_MAC = (
    "Ти заходиш у Макдак. Запах картоплі фрі збиває з ніг. За касою дівчина років 19 з яскравим волоссям.\n\n"
    " -  Вітаю! Бачу стрічку, парфуми, насіння в кишені, чую музику в голові… ти наш клієнт. "
    "Сьогодні акція для «туристів з минулого»: Big Mac + унікальний баф «Дух 2021» + «Запах фрі» + бонус «Київський смак». "
    "Хочеш активувати?"
)

# ТАК, активуй усе! - перемога квесту, інвентар доповнено
PORTAL_QUEST_VICTORY_TEXT = (
    "<b>ВІТАЄМО! ТИ ПЕРЕМІГ У КВЕСТІ «З 1937-го ДО МАКДАКУ 2021»!</b>\n\n"
    "Ваш інвентар доповнено новими бафами!\n"
    "• Пальоні парфуми Gucci\n"
    "• Кольорова стрічка\n"
    "• Стаканчик насіння\n"
    "• «Дух 2021»\n"
    "• «Запах фрі»\n"
    "• «Київський смак»\n\n"
    "Ознайомитися з дією бафів та перевірити свій інвентар:\n"
    "/profile - Мої бафи\n\n"
    "Що робимо далі?"
)

# Назад у 37-й - альтернативний фінал, без вибору бафа
PORTAL_MAC_NO = (
    "Ти тиснеш на кнопку порталу. Повернення в 1937-й. Але тепер ти пахнеш фрі і сучасністю. "
    "У селі тебе зустрічають як «того, хто бачив майбутнє і вижив». Репутація +∞ серед місцевих."
)

# Я поспішаю - тишу, портал назад. Кінець гри, без нагороди.
PORTAL_MUSICIAN_REFUSE_END = (
    "Музикант: «Тоді слухай тишу!» Кличке когось - портал. Назад у 1937-й."
)

# Дякую, на дієті - портал назад. Кінець гри, без нагороди.
PORTAL_SEEDS_REFUSE_END = (
    "Бабуся: «Молодь пішла… без насіння - без душі!» Клацає пальцями - портал. Назад у 30-ті."
)

# Я з 1937-го, стрічки пох - сторіз, портал назад. Кінець гри, без нагороди.
PORTAL_RIBBON_REFUSE_END = (
    "Дівчата переглядаються: «Це шо, з минулого століття?»\n"
    "Тебе фотографують на телефон, постять у сторіз з підписом «time traveler fail». Портал активується. Назад у 30-ті."
)

# Пиздець парфумам - портал у Сицилію 30-х. Кінець гри, без нагороди.
PORTAL_PERFUME_REFUSE_END = (
    "Мужик кричить: «Ах ти курва стара!» - і викликає портал. Тебе викидає назад у Сицилію 30-х.\n\n"
    "«Ти пахнеш як раніше - потом, тютюном і поразкою.»"
)

# Вибір «Давай бий, гівнюк» - смерть. Кінець, без нагороди.
PORTAL_FIGHT_DEATH = (
    "Він дістає вирваний з кореня «Укрзалізниці» кийок. "
    "Ти помираєш на пероні 2021 року від травм, несумісних з життям у 1937-му."
)

PORTAL_REWARD_CHOICE_TEXT = (
    "🌀 <b>Кінець шляху</b> 🌀\n\n"
    "Тіні розступаються. Перед тобою - вибір унікальної нагороди.\n\n"
    "Обери один баф - він буде тільки твій і працюватиме в групах з режимом «Тільки унікальні бафи»."
)


@router_buff_shop.callback_query(F.data == "portal_entry")
async def portal_entry_cb(callback: CallbackQuery):
    """Вхід у портал з головного меню магазину."""
    if not _is_private_callback(callback):
        await callback.answer("🛒 Доступ лише в ЛС.", show_alert=True)
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        text = emoji_to_premium(
            "🌀 <b>Портал</b> 🌀\n\n"
            "Спочатку купи «Прохід у портал» в магазині (розділ «Придбати»).\n\n"
            "Портал одноразовий: після проходження щоб зайти знову - купи прохід знову."
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="Повернутися", callback_data="buffshop_back")
        kb.adjust(1)
        try:
            await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="html")
        except TelegramBadRequest:
            await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="html")
        await callback.answer()
        return
    completed_at, reward_granted = get_portal_progress(user_id)
    if reward_granted:
        # Не відбираємо прохід тут - користувач міг щойно купити повторно; списуємо при вході (portal_start)
        text = emoji_to_premium(
            "🌀 <b>Портал</b> 🌀\n\n"
            "Ти вже пройшов портал і отримав унікальну нагороду.\n\n"
            "Можна пройти сюжет знову (нагороду дають лише один раз)."
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="Увійти в портал", callback_data="portal_start")
        kb.button(text="Повернутися", callback_data="buffshop_back")
        kb.adjust(1)
    else:
        text = emoji_to_premium(
            "🌀 <b>Портал</b> 🌀\n\n"
            "Ти маєш прохід. За порогом чекає сюжет і унікальні бафи.\n\n"
            "Увійти?"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="Увійти в портал", callback_data="portal_start")
        kb.button(text="Повернутися", callback_data="buffshop_back")
        kb.adjust(1)
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="html")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="html")
    await callback.answer()


def _portal_video_path(scene_key: str) -> Optional[str]:
    """Повертає абсолютний шлях до відео сцени, якщо файл існує; інакше None."""
    rel = PORTAL_VIDEOS.get(scene_key)
    if not rel:
        return None
    # Перевіряємо відносно поточної робочої директорії
    for base in (os.getcwd(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        path = os.path.join(base, rel) if os.path.isabs(rel) else os.path.normpath(os.path.join(base, rel))
        if os.path.isfile(path):
            return path
    return None


@router_buff_shop.callback_query(F.data == "portal_start")
async def portal_start_cb(callback: CallbackQuery):
    """Початок сюжету порталу: репліка про майбутнє, 300 лір, кнопки «Купити портал» / «Я не лох»."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Купити портал", callback_data="portal_buy_enter")
    kb.button(text="Я не лох, відчепися", callback_data="portal_refuse")
    kb.adjust(1)
    video_path = _portal_video_path("start")
    try:
        await callback.message.delete()
    except Exception:
        pass
    if video_path:
        await callback.bot.send_video(
            chat_id=user_id,
            video=FSInputFile(video_path),
            caption=emoji_to_premium(PORTAL_STORY_START),
            reply_markup=kb.as_markup(),
            parse_mode="html",
        )
    else:
        await callback.bot.send_message(
            chat_id=user_id,
            text=emoji_to_premium(PORTAL_STORY_START),
            reply_markup=kb.as_markup(),
            parse_mode="html",
        )
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_buy_enter")
async def portal_buy_enter_cb(callback: CallbackQuery):
    """Сплатити 300 лір і перейти до наступної сцени порталу."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    if not reward_granted:
        balance = _get_balance(user_id)
        if balance < PORTAL_ENTRY_PRICE_CARB:
            await callback.answer(
                f"Недостатньо лір. Потрібно {PORTAL_ENTRY_PRICE_CARB}.",
                show_alert=True,
            )
            return
        _db_execute_sync(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s",
            (PORTAL_ENTRY_PRICE_CARB, user_id),
        )
        _db_commit_sync()
    # Сцена: вокзал, мужик з автобусом у Польщу
    kb = InlineKeyboardBuilder()
    kb.button(text="Го в Польщу, давай квиток", callback_data="portal_poland_yes")
    kb.button(text="Нах@й твою Польщу", callback_data="portal_poland_no")
    kb.adjust(1)
    video_path = _portal_video_path("station")
    if video_path:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.bot.send_video(
            chat_id=user_id,
            video=FSInputFile(video_path),
            caption=emoji_to_premium(PORTAL_STATION),
            reply_markup=kb.as_markup(),
            parse_mode="html",
        )
    else:
        has_media = getattr(callback.message, "video", None) is not None
        try:
            if has_media:
                await callback.message.edit_caption(caption=emoji_to_premium(PORTAL_STATION), reply_markup=kb.as_markup(), parse_mode="html")
            else:
                await callback.message.edit_text(emoji_to_premium(PORTAL_STATION), reply_markup=kb.as_markup(), parse_mode="html")
        except TelegramBadRequest:
            await callback.message.answer(emoji_to_premium(PORTAL_STATION), reply_markup=kb.as_markup(), parse_mode="html")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_refuse")
async def portal_refuse_cb(callback: CallbackQuery):
    """Відмова від порталу - репліка й кінець. Прохід списується - щоб спробувати знову, потрібно купити."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    has_media = getattr(callback.message, "video", None) is not None
    try:
        if has_media:
            await callback.message.edit_caption(caption=emoji_to_premium(PORTAL_REFUSE_TEXT), reply_markup=kb.as_markup(), parse_mode="html")
        else:
            await callback.message.edit_text(emoji_to_premium(PORTAL_REFUSE_TEXT), reply_markup=kb.as_markup(), parse_mode="html")
    except TelegramBadRequest:
        await callback.message.answer(emoji_to_premium(PORTAL_REFUSE_TEXT), reply_markup=kb.as_markup(), parse_mode="html")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_poland_yes")
async def portal_poland_yes_cb(callback: CallbackQuery):
    """Го в Польщу - повернення в 1937, усі знають що здався. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_POLAND_YES_END, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_poland_no")
async def portal_poland_no_cb(callback: CallbackQuery):
    """Нах@й твою Польщу - мужик злий, кнопки ВТЄКТИ / Давай бий. Без відео - тільки текст."""
    if not _is_private_callback(callback):
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="ВТЄКТИ", callback_data="portal_run")
    kb.button(text="Давай бий, гівнюк", callback_data="portal_fight")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_ANGRY, kb)
    await callback.answer()


async def _portal_edit_or_send(callback: CallbackQuery, text: str, kb: InlineKeyboardBuilder):
    """Редагує повідомлення (текст або caption) або відправляє нове. Текст обгортається в emoji_to_premium (🌀 тощо)."""
    body = emoji_to_premium(text)
    has_media = getattr(callback.message, "video", None) is not None
    try:
        if has_media:
            await callback.message.edit_caption(caption=body, reply_markup=kb.as_markup(), parse_mode="html")
        else:
            await callback.message.edit_text(body, reply_markup=kb.as_markup(), parse_mode="html")
    except TelegramBadRequest:
        await callback.message.answer(body, reply_markup=kb.as_markup(), parse_mode="html")


async def _portal_send_scene(
    callback: CallbackQuery, user_id: int, text: str, kb: InlineKeyboardBuilder, scene_key: str
) -> None:
    """Якщо є відео для scene_key - видаляє повідомлення і відправляє відео з підписом; інакше редагує текст/caption."""
    video_path = _portal_video_path(scene_key)
    if video_path:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.bot.send_video(
            chat_id=user_id,
            video=FSInputFile(video_path),
            caption=emoji_to_premium(text),
            reply_markup=kb.as_markup(),
            parse_mode="html",
        )
    else:
        await _portal_edit_or_send(callback, text, kb)


@router_buff_shop.callback_query(F.data == "portal_run")
async def portal_run_cb(callback: CallbackQuery):
    """ВТЄКТИ - відео (сцена 3, площа), потім текст про парфуми."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Купити парфуми ({PORTAL_PERFUME_PRICE_CARB} лір)", callback_data="portal_perfume_buy")
    kb.button(text="Пиздець тобі з твоїми парфумами", callback_data="portal_perfume_refuse")
    kb.adjust(1)
    # Відео 3 сцени (площа) перенесено сюди з екрану «Ти шо, сепар?»
    await _portal_send_scene(callback, user_id, PORTAL_SQUARE, kb, "scene_3")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_fight")
async def portal_fight_cb(callback: CallbackQuery):
    """Давай бий - смерть на пероні. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_FIGHT_DEATH, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_perfume_refuse")
async def portal_perfume_refuse_cb(callback: CallbackQuery):
    """Пиздець парфумам - портал у Сицилію 30-х. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_PERFUME_REFUSE_END, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_perfume_buy")
async def portal_perfume_buy_cb(callback: CallbackQuery):
    """Купити парфуми (150 лір) - далі вибір унікальної нагороди."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    if not reward_granted:
        balance = _get_balance(user_id)
        if balance < PORTAL_PERFUME_PRICE_CARB:
            await callback.answer(
                f"Недостатньо лір. Потрібно {PORTAL_PERFUME_PRICE_CARB}.",
                show_alert=True,
            )
            return
        _db_execute_sync(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s",
            (PORTAL_PERFUME_PRICE_CARB, user_id),
        )
        _db_commit_sync()
    # Парфуми куплено - йдеш далі, сцена на Хрещатику з дівчатами та стрічками
    text = PORTAL_PERFUME_BUY_SUCCESS + "\n\n" + PORTAL_KRESHCHATIK
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Купити стрічку ({PORTAL_RIBBON_PRICE_CARB} лір)", callback_data="portal_ribbon_buy")
    kb.button(text="Я з 1937-го, мені ваші стрічки пох", callback_data="portal_ribbon_refuse")
    kb.adjust(1)
    await _portal_send_scene(callback, user_id, text, kb, "scene_4")  # 4 сцена - Хрещатик, дівчата з стрічками
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_ribbon_refuse")
async def portal_ribbon_refuse_cb(callback: CallbackQuery):
    """Я з 1937-го, стрічки пох - сторіз, портал назад. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_RIBBON_REFUSE_END, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_ribbon_buy")
async def portal_ribbon_buy_cb(callback: CallbackQuery):
    """Купити стрічку (100 лір) - далі вибір унікальної нагороди."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    if not reward_granted:
        balance = _get_balance(user_id)
        if balance < PORTAL_RIBBON_PRICE_CARB:
            await callback.answer(
                f"Недостатньо лір. Потрібно {PORTAL_RIBBON_PRICE_CARB}.",
                show_alert=True,
            )
            return
        _db_execute_sync(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s",
            (PORTAL_RIBBON_PRICE_CARB, user_id),
        )
        _db_commit_sync()
    # Стрічку куплено - 5 сцена (таксі Lacetti)
    text = PORTAL_RIBBON_BUY_SUCCESS + "\n\n" + PORTAL_TAXI
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Сісти в таксі ({PORTAL_TAXI_PRICE_CARB} лір)", callback_data="portal_taxi_yes")
    kb.button(text="Пішки піду", callback_data="portal_taxi_no")
    kb.adjust(1)
    await _portal_send_scene(callback, user_id, text, kb, "scene_5")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_taxi_yes")
async def portal_taxi_yes_cb(callback: CallbackQuery):
    """Сісти в таксі - об'їзд, викидає, портал назад. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    revoke_portal_access(user_id)
    _, reward_granted = get_portal_progress(user_id)
    if not reward_granted:
        balance = _get_balance(user_id)
        if balance < PORTAL_TAXI_PRICE_CARB:
            await callback.answer(
                f"Недостатньо лір. Потрібно {PORTAL_TAXI_PRICE_CARB}.",
                show_alert=True,
            )
            return
        _db_execute_sync(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s",
            (PORTAL_TAXI_PRICE_CARB, user_id),
        )
        _db_commit_sync()
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_TAXI_YES_END, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_taxi_no")
async def portal_taxi_no_cb(callback: CallbackQuery):
    """Пішки піду - далі бабуся з насінням біля переходу."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    text = PORTAL_TAXI_NO_SUCCESS + "\n\n" + PORTAL_GRANDMA
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Купити насіння ({PORTAL_SEEDS_PRICE_CARB} лір)", callback_data="portal_seeds_buy")
    kb.button(text="Дякую, бабусю, я на дієті", callback_data="portal_seeds_refuse")
    kb.adjust(1)
    await _portal_send_scene(callback, user_id, text, kb, "scene_6")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_seeds_refuse")
async def portal_seeds_refuse_cb(callback: CallbackQuery):
    """Дякую, на дієті - портал назад. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_SEEDS_REFUSE_END, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_seeds_buy")
async def portal_seeds_buy_cb(callback: CallbackQuery):
    """Купити насіння (50 лір) - далі вибір унікальної нагороди."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    if not reward_granted:
        balance = _get_balance(user_id)
        if balance < PORTAL_SEEDS_PRICE_CARB:
            await callback.answer(
                f"Недостатньо лір. Потрібно {PORTAL_SEEDS_PRICE_CARB}.",
                show_alert=True,
            )
            return
        _db_execute_sync(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s",
            (PORTAL_SEEDS_PRICE_CARB, user_id),
        )
        _db_commit_sync()
    # Насіння куплено - 7 сцена (перевірка хлопців з раціями)
    text = PORTAL_SEEDS_BUY_SUCCESS + "\n\n" + PORTAL_CHECK
    kb = InlineKeyboardBuilder()
    kb.button(text="Сказати: «Київ - найкраще місто!»", callback_data="portal_kyiv_yes")
    kb.button(text="Я з 1937 року, тоді Палермо було крутіше", callback_data="portal_kyiv_refuse")
    kb.adjust(1)
    await _portal_send_scene(callback, user_id, text, kb, "scene_7")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_kyiv_refuse")
async def portal_kyiv_refuse_cb(callback: CallbackQuery):
    """Я з 1937, Палермо крутіше - провокація, портал назад. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_KYIV_REFUSE_END, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_kyiv_yes")
async def portal_kyiv_yes_cb(callback: CallbackQuery):
    """Сказати «Київ - найкраще місто!» - далі музикант біля переходу."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    text = PORTAL_KYIV_YES_SUCCESS + "\n\n" + PORTAL_MUSICIAN
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Скинути {PORTAL_MUSICIAN_PRICE_CARB} лір і послухати", callback_data="portal_musician_buy")
    kb.button(text="Я поспішаю", callback_data="portal_musician_refuse")
    kb.adjust(1)
    await _portal_send_scene(callback, user_id, text, kb, "scene_8")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_musician_refuse")
async def portal_musician_refuse_cb(callback: CallbackQuery):
    """Я поспішаю - тишу, портал назад. Кінець гри, без нагороди. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_MUSICIAN_REFUSE_END, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_musician_buy")
async def portal_musician_buy_cb(callback: CallbackQuery):
    """Скинути 50 лір музиканту - далі вибір унікальної нагороди."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    if not reward_granted:
        balance = _get_balance(user_id)
        if balance < PORTAL_MUSICIAN_PRICE_CARB:
            await callback.answer(
                f"Недостатньо лір. Потрібно {PORTAL_MUSICIAN_PRICE_CARB}.",
                show_alert=True,
            )
            return
        _db_execute_sync(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s",
            (PORTAL_MUSICIAN_PRICE_CARB, user_id),
        )
        _db_commit_sync()
    # Донат музиканту - 9 сцена (Макдак, касирка й акція)
    text = PORTAL_MUSICIAN_BUY_SUCCESS + "\n\n" + PORTAL_MAC
    kb = InlineKeyboardBuilder()
    kb.button(text="ТАК, активуй усе!", callback_data="portal_mac_yes")
    kb.button(text="Я краще назад у 37-й, там хоч зрозуміло, де що коштує", callback_data="portal_mac_no")
    kb.adjust(1)
    await _portal_send_scene(callback, user_id, text, kb, "scene_9")
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_mac_no")
async def portal_mac_no_cb(callback: CallbackQuery):
    """Назад у 37-й - альтернативний фінал (репутація +∞), без унікального бафа. Прохід списується."""
    if not _is_private_callback(callback):
        return
    revoke_portal_access(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_MAC_NO, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data == "portal_mac_yes")
async def portal_mac_yes_cb(callback: CallbackQuery):
    """ТАК, активуй усе! - видача всіх унікальних бафів порталу одразу."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    if reward_granted:
        # Відновлення: якщо бафів немає або не всі 6 - видати відсутні
        missing = _get_missing_portal_buff_ids(user_id)
        if missing:
            granted = 0
            for bid in missing:
                if grant_portal_reward(user_id, bid):
                    granted += 1
            if granted > 0:
                revoke_portal_access(user_id)
                kb = InlineKeyboardBuilder()
                kb.button(text="Повернутися", callback_data="buffshop_back")
                kb.adjust(1)
                await _portal_edit_or_send(callback, PORTAL_QUEST_VICTORY_TEXT, kb)
                msg = "Усі бафи отримано!  (відновлено)" if granted == len(missing) == len(PORTAL_QUEST_REWARD_IDS) else f"Додано відсутні бафи: {granted} шт. "
                await callback.answer(msg, show_alert=True)
                return
        # Реплей: нагороду не даємо, прохід списуємо в кінці
        revoke_portal_access(user_id)
        kb = InlineKeyboardBuilder()
        kb.button(text="Повернутися", callback_data="buffshop_back")
        kb.adjust(1)
        await _portal_edit_or_send(callback, PORTAL_QUEST_VICTORY_TEXT, kb)
        await callback.answer("Сюжет пройдено ще раз.", show_alert=True)
        return
    granted = 0
    for bid in PORTAL_QUEST_REWARD_IDS:
        if grant_portal_reward(user_id, bid):
            granted += 1
    if not granted:
        await callback.answer("Помилка видачі нагород.", show_alert=True)
        return
    set_portal_completed(user_id, reward_granted=True)
    revoke_portal_access(user_id)  # Портал одноразовий - щоб зайти знову, потрібно купити «Прохід у портал» знову
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, PORTAL_QUEST_VICTORY_TEXT, kb)
    await callback.answer("Усі бафи отримано! ", show_alert=True)


@router_buff_shop.callback_query(F.data.startswith("portal_next_"))
async def portal_next_cb(callback: CallbackQuery):
    """Крок сюжету (резерв: прямий перехід до вибору нагороди)."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    step = (callback.data or "").split("_")[-1]
    if step == "1":
        kb = InlineKeyboardBuilder()
        for uid, item in UNIQUE_BUFFS.items():
            kb.button(text=f"{item.emoji} {item.name}", callback_data=f"portal_reward:{uid}")
        kb.adjust(1)
        await _portal_edit_or_send(callback, PORTAL_REWARD_CHOICE_TEXT, kb)
    await callback.answer()


@router_buff_shop.callback_query(F.data.startswith("portal_reward:"))
async def portal_reward_cb(callback: CallbackQuery):
    """Видача обраного унікального бафа та завершення порталу."""
    if not _is_private_callback(callback):
        return
    user_id = callback.from_user.id
    if not has_portal_access(user_id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    _, reward_granted = get_portal_progress(user_id)
    if reward_granted:
        revoke_portal_access(user_id)
        kb = InlineKeyboardBuilder()
        kb.button(text="Повернутися", callback_data="buffshop_back")
        kb.adjust(1)
        await _portal_edit_or_send(callback, PORTAL_QUEST_VICTORY_TEXT, kb)
        await callback.answer("Нагороду вже отримано.", show_alert=True)
        return
    unique_buff_id = (callback.data or "").split(":", 1)[-1]
    if unique_buff_id not in UNIQUE_BUFFS:
        await callback.answer("Невірна нагорода.", show_alert=True)
        return
    if not grant_portal_reward(user_id, unique_buff_id):
        await callback.answer("Помилка видачі.", show_alert=True)
        return
    set_portal_completed(user_id, reward_granted=True)
    revoke_portal_access(user_id)  # Портал одноразовий
    item = UNIQUE_BUFFS[unique_buff_id]
    text = (
        f"🎁 <b>Нагорода порталу</b> 🎁\n\n"
        f"Ти отримав: {item.emoji} <b>{item.name}</b>.\n\n"
        "Цей баф унікальний і працює в групах, де увімкнено «Тільки унікальні бафи»."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="Повернутися", callback_data="buffshop_back")
    kb.adjust(1)
    await _portal_edit_or_send(callback, text, kb)
    await callback.answer("Нагороду отримано! ", show_alert=True)

