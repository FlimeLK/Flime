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
        return self.name


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
        Item(OBEREG, "Оберіг", "🧿", 120, "Рятує від однієї нічної смерті."),
        Item(GARLIC, "Часник", "🧄", 60, "Мавка не зможе тебе заманити."),
        Item(HORSESHOE, "Підкова", "🐴", 150, "Один раз рятує від страти громадою."),
        Item(CANDLE, "Свічка", "🕯", 70, "Зранку покаже, хто вночі приходив до твоєї хати."),
        Item(MASK, "Маска колядника", "🎭", 90, "Характерник побачить тебе як чесного селянина."),
        Item(PITCHFORK, "Вила", "🔱", 200, "Одне нічне вбивство будь-кого на твій вибір.", active=True),
        Item(HONEY, "Мед", "🍯", 80, "Твій голос на денному голосуванні важить подвійно.", active=True),
    )
}

# Порядок, у якому предмети з інвентарю беруться в кишеню на гру.
POCKET_ORDER = [OBEREG, HORSESHOE, PITCHFORK, MASK, GARLIC, CANDLE, HONEY]
BASE_POCKET_SLOTS = 3
VIP_POCKET_SLOTS = 4
