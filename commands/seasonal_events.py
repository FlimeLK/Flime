# -*- coding: utf-8 -*-
"""
Сезонні івенти бота.

Один івент може бути активним одночасно (single-active). Активний івент
зберігається глобально в БД (таблиця seasonal_event_state), тож умикання/вимикання
з адмін-панелі діє відразу для всіх.

Поки що реєстр порожній — це лише інфраструктура. Щоб додати новий івент, додай
запис у SEASONAL_EVENTS за схемою нижче. Поле "features" — це місце під «доп. функції»
кожного івенту (бонуси, спец-ролі, множники тощо), які потім читає ігрова логіка.

Схема запису:
    {
        "id": "halloween",                # унікальний короткий код (<=64 символи, [a-z0-9_])
        "name": "Геловін",                # людська назва
        "emoji": "🎃",                    # емодзі для кнопок/тексту
        "description": "Опис івенту…",     # короткий опис (показується в адмін-панелі)
        "features": {                      # ← доп. функції/налаштування івенту (необов'язково)
            # "coin_multiplier": 2,
            # "special_role": "Гарбуз",
            # "night_message": "…",
        },
    }
"""

from typing import Optional, List, Dict, Any

from database.database import (
    get_active_seasonal_event,
    get_active_seasonal_event_async,
    set_active_seasonal_event,
    set_active_seasonal_event_async,
)

# ──────────────────────────────────────────────────────────────────────────
# Реєстр сезонних івентів. ПОКИ ПОРОЖНІЙ.
# Додавай нові івенти сюди за схемою з докстрингу вище.
# ──────────────────────────────────────────────────────────────────────────
SEASONAL_EVENTS: List[Dict[str, Any]] = [
    {
        "id": "kupala_night",
        "name": "Купальська ніч",
        "emoji": "☀️",
        "description": (
            "Літній івент: нові ролі (Русалка, Мисливець на русалку), збір інгредієнтів "
            "у лісі, крафт вінків і бафи «Щаслива ніч» та «Магія Купала»."
        ),
        # ── Доп. функції івенту (структурований ТЗ; читається ігровою логікою поетапно). ──
        "features": {
            # 1. Нові ролі
            "roles": {
                "mermaid": {
                    "name": "Русалка",
                    "emoji": "🧜",
                    "alignment": "good",
                    "abilities": {
                        "water_flow": {
                            "name": "Водний потік",
                            "type": "redirect",
                            "desc": "Обирає Гравця А та Гравця Б; атаку злих ролей з А переписує на Б.",
                            "priority": "after_block_before_attack",
                        },
                        "deep_charm": {
                            "name": "Оберіг глибин",
                            "type": "protect",
                            "desc": "Невразливість цілі на 1 ніч; далі сама Русалка «Виснажена» 1 ніч.",
                            "self_weakened_nights": 1,
                            "cannot_protect_self_twice": True,
                        },
                    },
                },
                "mermaid_hunter": {
                    "name": "Мисливець на русалку",
                    "emoji": "🩸",
                    "alignment": "neutral",
                    "goal": "Нейтралізація цілей; не залежить від перемоги мирних.",
                    "abilities": {
                        "ambush": {
                            "name": "Засідка",
                            "type": "silence",
                            "desc": "Ціль не може використати нічну дію (кд не повертається).",
                        },
                        "harpoon": {
                            "name": "Гарпун",
                            "type": "ultimate_attack",
                            "desc": "Атака, що ігнорує щити; Русалка не може її перенаправити.",
                            "uses_per_game": 1,
                            "ignore_shield": True,
                        },
                    },
                    "sees_mermaid_weakened": True,  # бачить статус «Виснаження» у Русалки
                },
            },
            # 2. Інгредієнти та крафт
            "ingredients": {
                "marigold": {"name": "Лимони", "emoji": "🏵"},
                "fern": {"name": "Гілочка папороті", "emoji": "🌿"},
            },
            "forest_trip": {
                "name": "Похід до лісу",
                "cooldown_hours": 24,
                "loot": [
                    {"item": "marigold", "chance": 100, "amount": [1, 2]},
                    {"item": "fern", "chance": 30, "requires_buff": "forest_trip_buff"},
                ],
            },
            "recipes": {
                "wreath_lucky": {
                    "name": "Вінок «Щаслива ніч»",
                    "cost": {"marigold": 3},
                    "grants_buff": "lucky_night",
                },
                "wreath_magic": {
                    "name": "Вінок «Магія Купала»",
                    "cost": {"marigold": 3, "fern": 3},
                    "grants_buff": "kupala_magic",
                },
            },
            # 3. Бафи
            "buffs": {
                "lucky_night": {
                    "name": "Щаслива ніч",
                    "emoji": "🟡",
                    "target_role": "Аль Капоне",
                    "effect": "ui_blank_targets",  # імена жертв → пусті кнопки; вибір випадковий
                    "duration_nights": 1,
                },
                "kupala_magic": {
                    "name": "Магія Купала",
                    "emoji": "🔮",
                    "effects": {
                        "defense_miss_percent": 50,  # вхідні нічні дії 50% → Miss
                        "extra_flower_count": 1,      # +1 квітка за збір цієї ночі
                    },
                },
                "forest_trip_buff": {
                    "name": "Похід до лісу",
                    "emoji": "🌿",
                    "effect": "fern_drop_chance",
                    "fern_chance_percent": 30,
                },
            },
            # 5. Балансні обмеження
            "balance": {
                "mermaid_no_self_protect_twice": True,
                "hunter_sees_weakened": True,
                "lucky_night_one_game_night": True,
            },
        },
    },
]


def list_events() -> List[Dict[str, Any]]:
    """Усі зареєстровані івенти."""
    return list(SEASONAL_EVENTS)


def get_event(event_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Знайти івент за id (або None)."""
    if not event_id:
        return None
    for ev in SEASONAL_EVENTS:
        if ev.get("id") == event_id:
            return ev
    return None


def event_label(event_id: Optional[str]) -> str:
    """Зручний підпис «емодзі + назва» для івенту (або сам id, якщо не знайдено)."""
    ev = get_event(event_id)
    if not ev:
        return str(event_id) if event_id else "—"
    emoji = ev.get("emoji", "")
    name = ev.get("name", ev.get("id", ""))
    return f"{emoji} {name}".strip()


# ── Активний івент ──────────────────────────────────────────────────────────

def get_active_event_id_sync() -> Optional[str]:
    """Синхронно: id активного івенту (для коду без async, напр. GameState)."""
    return get_active_seasonal_event()


async def get_active_event_id() -> Optional[str]:
    """Async: id активного івенту."""
    return await get_active_seasonal_event_async()


async def get_active_event() -> Optional[Dict[str, Any]]:
    """Async: повний запис активного івенту (або None)."""
    return get_event(await get_active_seasonal_event_async())


async def set_active_event(event_id: Optional[str]) -> bool:
    """
    Увімкнути івент (передай id) або вимкнути всі (передай None).
    Single-active: попередній активний автоматично замінюється.
    Якщо id передано, але такого івенту в реєстрі немає — відмова.
    """
    if event_id is not None and get_event(event_id) is None:
        return False
    return await set_active_seasonal_event_async(event_id)


async def disable_active_event() -> bool:
    """Вимкнути будь-який активний івент (для всіх)."""
    return await set_active_seasonal_event_async(None)


# ── Доступ до «доп. функцій» активного/конкретного івенту ────────────────────

def event_features(event_id: Optional[str]) -> Dict[str, Any]:
    """Словник доп. функцій/налаштувань івенту (порожній, якщо немає)."""
    ev = get_event(event_id)
    if not ev:
        return {}
    return dict(ev.get("features") or {})


def event_feature(event_id: Optional[str], key: str, default: Any = None) -> Any:
    """Одна доп. функція/налаштування івенту за ключем."""
    return event_features(event_id).get(key, default)
