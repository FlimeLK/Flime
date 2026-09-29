"""Опис ролей гри «Мафія: Хутір».

Ролі описані як дані. Поведінку нічних дій визначає `NightKind`,
а резолвер ночі (engine/night.py) обробляє кожен вид дії в одному місці.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Team(StrEnum):
    VILLAGE = "village"   # Мирні
    EVIL = "evil"         # Мафія
    WOLF = "wolf"         # Маніяк (одинак)
    FOOL = "fool"         # Самогубець (одинак)


class NightKind(StrEnum):
    KILL = "kill"          # голос мафії за жертву
    HEAL = "heal"          # лікар
    CHECK = "check"        # комісар: перевірка
    SABER = "saber"        # комісар: постріл (1 раз)
    WATCH = "watch"        # волоцюга
    COMPARE = "compare"    # журналіст: дві цілі
    LURE = "lure"          # коханка
    WOLF_KILL = "wolf"     # маніяк
    PITCHFORK = "pitchfork"  # предмет «Вила»
    CUSTOM_KILL = "ckill"  # власна роль-вбивця (не з мафії)


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
    # Для власних ролей чату: опис і premium-емодзі.
    description: str = ""
    custom_emoji_id: str | None = None
    custom: bool = False

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


ROLES: dict[str, Role] = {
    r.key: r
    for r in (
        Role("selianyn", "Мирний житель", "🙂", Team.VILLAGE, optional=False),
        Role("znaharka", "Лікар", "👨‍⚕️", Team.VILLAGE, (NightKind.HEAL,), min_players=4),
        Role("harakternyk", "Комісар", "🕵️", Team.VILLAGE, (NightKind.CHECK, NightKind.SABER), min_players=5),
        Role("kum", "Щасливчик", "🍀", Team.VILLAGE, min_players=6),
        Role("storozh", "Волоцюга", "🚶", Team.VILLAGE, (NightKind.WATCH,), min_players=8),
        Role("kobzar", "Журналіст", "📰", Team.VILLAGE, (NightKind.COMPARE,), min_players=9),
        Role("otaman", "Мер", "🎖", Team.VILLAGE, min_players=11),
        Role("vidma", "Дон", "🎩", Team.EVIL, (NightKind.KILL,), optional=False),
        Role("upyr", "Мафія", "🔫", Team.EVIL, (NightKind.KILL,), optional=False),
        Role("mavka", "Коханка", "💋", Team.EVIL, (NightKind.LURE,), min_players=6),
        Role("vovkulaka", "Маніяк", "🔪", Team.WOLF, (NightKind.WOLF_KILL,), min_players=10),
        Role("duren", "Самогубець", "🤡", Team.FOOL, min_players=7),
    )
}

TEAM_TITLES = {
    Team.VILLAGE: "🏠 Мирні",
    Team.EVIL: "🌑 Мафія",
    Team.WOLF: "🔪 Маніяк",
    Team.FOOL: "🤡 Самогубець",
}


def role(key: str) -> Role:
    return ROLES[key]


# ---------- власні ролі чату ----------
# Адмін обирає шаблон здатності; він перетворюється на наявні нічні дії рушія.

ABILITIES: dict[str, str] = {
    "kill": "Вбивати",
    "heal": "Лікувати",
    "check": "Перевіряти",
    "block": "Блокувати",
    "watch": "Стежити",
    "none": "Без дії",
}


def ability_kinds(ability: str, team: Team) -> tuple[NightKind, ...]:
    if ability == "kill":
        # Нечисть вбиває спільним голосуванням, решта - самостійно.
        return (NightKind.KILL,) if team == Team.EVIL else (NightKind.CUSTOM_KILL,)
    return {
        "heal": (NightKind.HEAL,),
        "check": (NightKind.CHECK,),
        "block": (NightKind.LURE,),
        "watch": (NightKind.WATCH,),
    }.get(ability, ())


def custom_key(role_id: int) -> str:
    return f"c{role_id}"


def custom_role(d: dict) -> Role:
    """Роль з запису БД / знімка гри: id, name, emoji, emoji_id, description, team, ability, min_players."""
    team = Team(d["team"])
    return Role(
        key=custom_key(d["id"]), name=d["name"], emoji=d["emoji"], team=team,
        night=ability_kinds(d["ability"], team), min_players=d["min_players"],
        description=d.get("description", ""), custom_emoji_id=d.get("emoji_id"), custom=True,
    )


def register_custom(dicts: list[dict]) -> list[str]:
    """Додає власні ролі в реєстр (ключі глобально унікальні - id з БД). Повертає їхні ключі."""
    keys = []
    for d in dicts:
        r = custom_role(d)
        ROLES[r.key] = r
        keys.append(r.key)
    return keys
