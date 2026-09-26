"""Розподіл ролей між гравцями."""

from __future__ import annotations

import random
from collections.abc import Iterable

from bot.engine.models import MAX_PLAYERS, MIN_PLAYERS, Game, Phase

# Спеціальні ролі в порядку появи (кожна — з певної кількості гравців, див. roles.py).
VILLAGE_SPECIALS = ["znaharka", "harakternyk", "kum", "storozh", "kobzar", "otaman"]
SOLO_ROLES = ["duren", "vovkulaka"]


def evil_count(n: int) -> int:
    return max(1, round(n / 3.5))


def build_roles(n: int, disabled: Iterable[str] = ()) -> list[str]:
    """Повертає список ролей довжини n (ще не перемішаний)."""
    from bot.engine.roles import ROLES

    if not MIN_PLAYERS <= n <= MAX_PLAYERS:
        raise ValueError(f"players must be in {MIN_PLAYERS}..{MAX_PLAYERS}")
    off = {k for k in disabled if ROLES.get(k) and ROLES[k].optional}

    def enabled(key: str) -> bool:
        return key not in off and n >= ROLES[key].min_players

    evil = evil_count(n)
    roles = ["vidma"]
    if evil >= 2 and enabled("mavka"):
        roles.append("mavka")
    roles += ["upyr"] * (evil - len(roles))

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
    roles = build_roles(len(ids), game.settings.get("disabled_roles", ()))
    rng.shuffle(roles)
    for uid, role in zip(ids, roles, strict=True):
        p = game.players[uid]
        p.role = role
        p.alive = True
        p.flags = {}
    game.phase = Phase.NIGHT
    game.day = 1
