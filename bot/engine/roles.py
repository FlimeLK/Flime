"""Опис ролей гри «Мафія: Хутір».

Ролі описані як дані. Поведінку нічних дій визначає `NightKind`,
а резолвер ночі (engine/night.py) обробляє кожен вид дії в одному місці.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Team(StrEnum):
    VILLAGE = "village"   # Громада
    EVIL = "evil"         # Нечисть
    WOLF = "wolf"         # Вовкулака (одинак)
    FOOL = "fool"         # Іван-дурень (одинак)


class NightKind(StrEnum):
    KILL = "kill"          # голос нечисті за жертву
    HEAL = "heal"          # знахарка
    CHECK = "check"        # характерник: перевірка
    SABER = "saber"        # характерник: удар шаблею (1 раз)
    WATCH = "watch"        # сторож
    COMPARE = "compare"    # кобзар: дві цілі
    LURE = "lure"          # мавка
    WOLF_KILL = "wolf"     # вовкулака
    PITCHFORK = "pitchfork"  # предмет «Вила»


@dataclass(frozen=True)
class Role:
    key: str
    name: str
    emoji: str
    team: Team
    night: tuple[NightKind, ...] = ()
    # Мінімальна кількість гравців, з якої роль з'являється в грі.
    min_players: int = 0
    # Чи може адміністратор чату вимкнути роль.
    optional: bool = True

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


ROLES: dict[str, Role] = {
    r.key: r
    for r in (
        Role("selianyn", "Селянин", "👨‍🌾", Team.VILLAGE, optional=False),
        Role("znaharka", "Знахарка", "🌿", Team.VILLAGE, (NightKind.HEAL,), min_players=4),
        Role("harakternyk", "Характерник", "🗡", Team.VILLAGE, (NightKind.CHECK, NightKind.SABER), min_players=5),
        Role("kum", "Кум", "🍀", Team.VILLAGE, min_players=6),
        Role("storozh", "Сторож", "🏮", Team.VILLAGE, (NightKind.WATCH,), min_players=8),
        Role("kobzar", "Кобзар", "🪕", Team.VILLAGE, (NightKind.COMPARE,), min_players=9),
        Role("otaman", "Отаман", "🎖", Team.VILLAGE, min_players=11),
        Role("vidma", "Відьма", "🧙‍♀️", Team.EVIL, (NightKind.KILL,), optional=False),
        Role("upyr", "Упир", "🧛", Team.EVIL, (NightKind.KILL,), optional=False),
        Role("mavka", "Мавка", "🧜‍♀️", Team.EVIL, (NightKind.LURE,), min_players=6),
        Role("vovkulaka", "Вовкулака", "🐺", Team.WOLF, (NightKind.WOLF_KILL,), min_players=10),
        Role("duren", "Іван-дурень", "🤪", Team.FOOL, min_players=7),
    )
}

TEAM_TITLES = {
    Team.VILLAGE: "🌾 Громада",
    Team.EVIL: "🌑 Нечисть",
    Team.WOLF: "🐺 Вовкулака",
    Team.FOOL: "🤪 Іван-дурень",
}


def role(key: str) -> Role:
    return ROLES[key]
