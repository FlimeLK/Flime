"""Розподіл ролей між гравцями."""

from __future__ import annotations

import random
from collections.abc import Iterable

from bot.engine.models import MAX_PLAYERS, MIN_PLAYERS, Game, Phase

# Спеціальні ролі в порядку появи (кожна - з певної кількості гравців, див. roles.py).
VILLAGE_SPECIALS = ["znaharka", "harakternyk", "kum", "storozh", "kobzar", "otaman"]
SOLO_ROLES = ["duren", "vovkulaka"]


# Розмір сім'ї (налаштування чату): скільки гравців припадає на одного мафіозі.
MAFIA_RATIOS = {"few": 4.5, "normal": 3.5, "many": 2.8}


def evil_count(n: int, ratio: str = "normal") -> int:
    return max(1, round(n / MAFIA_RATIOS.get(ratio, MAFIA_RATIOS["normal"])))


def build_roles(n: int, disabled: Iterable[str] = (), custom: Iterable[str] = (),
                ratio: str = "normal") -> list[str]:
    """Повертає список ролей довжини n (ще не перемішаний).

    custom - ключі власних ролей чату (уже зареєстрованих у ROLES); вони роздаються першими:
    мафія - замість рядових мафіозі (кількість мафії не змінюється), решта - перед стандартними спецролями.
    """
    from bot.engine.roles import ROLES

    if not MIN_PLAYERS <= n <= MAX_PLAYERS:
        raise ValueError(f"players must be in {MIN_PLAYERS}..{MAX_PLAYERS}")
    off = {k for k in disabled if ROLES.get(k) and ROLES[k].optional}

    def enabled(key: str) -> bool:
        return key not in off and n >= ROLES[key].min_players

    from bot.engine.roles import Team

    custom = [k for k in custom if k in ROLES and n >= ROLES[k].min_players]
    evil = evil_count(n, ratio)
    roles = ["vidma"]
    for key in custom:
        if ROLES[key].team == Team.EVIL and len(roles) < evil:
            roles.append(key)
    if len(roles) < evil and evil >= 2 and enabled("mavka"):
        roles.append("mavka")
    roles += ["upyr"] * (evil - len(roles))

    others = [k for k in custom if ROLES[k].team != Team.EVIL]
    for key in others:
        if len(roles) >= n - 1:  # лишаємо щонайменше одне місце для стандартних ролей
            break
        roles.append(key)
    for key in SOLO_ROLES + VILLAGE_SPECIALS:
        if len(roles) >= n:
            break
        if enabled(key):
            roles.append(key)
    roles += ["selianyn"] * (n - len(roles))
    return roles


def assign_roles(game: Game, rng: random.Random | None = None) -> None:
    rng = rng or random.Random()
    ids = list(game.players)
    from bot.engine.roles import register_custom

    custom = register_custom(game.settings.get("custom_roles", []))
    roles = build_roles(len(ids), game.settings.get("disabled_roles", ()), custom,
                        game.settings.get("mafia_ratio", "normal"))
    rng.shuffle(roles)
    for uid, role in zip(ids, roles, strict=True):
        p = game.players[uid]
        p.role = role
        p.alive = True
        p.flags = {}
    game.phase = Phase.NIGHT
    game.day = 1
