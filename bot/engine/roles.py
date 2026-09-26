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
    # Пасивні властивості: lucky — переживає перший напад, vote2 — подвійний голос на страті.
    passives: tuple[str, ...] = ()
    # Роль, створена адміністратором чату в конструкторі.
    custom: bool = False
    description: str = ""

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}" if self.emoji else self.name


ROLES: dict[str, Role] = {
    r.key: r
    for r in (
        Role("selianyn", "Селянин", "👨‍🌾", Team.VILLAGE, optional=False),
        Role("znaharka", "Знахарка", "🌿", Team.VILLAGE, (NightKind.HEAL,), min_players=4),
        Role("harakternyk", "Характерник", "🗡", Team.VILLAGE, (NightKind.CHECK, NightKind.SABER), min_players=5),
        Role("kum", "Кум", "🍀", Team.VILLAGE, min_players=6, passives=("lucky",)),
        Role("storozh", "Сторож", "🏮", Team.VILLAGE, (NightKind.WATCH,), min_players=8),
        Role("kobzar", "Кобзар", "🪕", Team.VILLAGE, (NightKind.COMPARE,), min_players=9),
        Role("otaman", "Отаман", "🎖", Team.VILLAGE, min_players=11, passives=("vote2",)),
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


# ---------- свої ролі чату ----------

# Здібності, які можна дати своїй ролі.
CUSTOM_ABILITIES = ("none", "heal", "check", "watch", "compare", "block", "kill", "lucky", "vote2")
CUSTOM_TEAMS = (Team.VILLAGE, Team.EVIL)

# Зареєстровані свої ролі всіх чатів: ключ «c<id>» унікальний, тож чати не перетинаються.
CUSTOM_ROLES: dict[str, Role] = {}


def custom_role(d: dict) -> Role:
    """Роль зі словника {key, name, team, ability, min_players, description}."""
    team = Team(d["team"])
    ability = d["ability"]
    night: tuple[NightKind, ...] = ()
    passives: tuple[str, ...] = ()
    if ability == "kill":
        # Нечисть голосує за жертву разом з усіма; інші — одне вбивство за гру.
        night = (NightKind.KILL,) if team == Team.EVIL else (NightKind.SABER,)
    elif ability in ("lucky", "vote2"):
        passives = (ability,)
    elif ability != "none":
        night = ({
            "heal": NightKind.HEAL, "check": NightKind.CHECK, "watch": NightKind.WATCH,
            "compare": NightKind.COMPARE, "block": NightKind.LURE,
        }[ability],)
    return Role(d["key"], d["name"], "🎭", team, night, min_players=int(d["min_players"]),
                passives=passives, custom=True, description=d.get("description", ""))


def register_custom(roles: list[dict]) -> list[Role]:
    result = []
    for d in roles:
        r = custom_role(d)
        CUSTOM_ROLES[r.key] = r
        result.append(r)
    return result


def role(key: str) -> Role:
    return ROLES.get(key) or CUSTOM_ROLES[key]
