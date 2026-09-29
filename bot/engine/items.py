"""Предмети, які можна купити в крамниці й узяти з собою в гру."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    emoji: str
    price: int
    description: str
    # Активні предмети гравець застосовує сам кнопкою, пасивні спрацьовують автоматично.
    active: bool = False

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


OBEREG = "obereg"
GARLIC = "garlic"
HORSESHOE = "horseshoe"
CANDLE = "candle"
MASK = "mask"
PITCHFORK = "pitchfork"
HONEY = "honey"

ITEMS: dict[str, Item] = {
    i.key: i
    for i in (
        Item(OBEREG, "Талісман", "📿", 120, "Рятує від однієї нічної смерті."),
        Item(GARLIC, "Парфум", "🧴", 60, "Коханка не зможе тебе заблокувати."),
        Item(HORSESHOE, "Чорний «Опель»", "🚗", 150, "Один раз вивозить тебе з площі до страти."),
        Item(CANDLE, "Ліхтарик", "🔦", 70, "Зранку покаже, хто вночі приходив до тебе."),
        Item(MASK, "Паспорт Лиса", "📜", 90, "Комісар побачить тебе як мирного жителя."),
        Item(PITCHFORK, "Заточка", "🔪", 200, "Одне нічне вбивство будь-кого на твій вибір.", active=True),
        Item(HONEY, "Сигара Дона", "🚬", 80, "Твій голос на денному голосуванні важить подвійно.", active=True),
    )
}

# Порядок, у якому предмети з інвентарю беруться в кишеню на гру.
POCKET_ORDER = [OBEREG, HORSESHOE, PITCHFORK, MASK, GARLIC, CANDLE, HONEY]
BASE_POCKET_SLOTS = 3
VIP_POCKET_SLOTS = 4
