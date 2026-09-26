"""Розподіл ролей між гравцями."""

from __future__ import annotations

import random
from collections.abc import Iterable

from bot.engine.models import MAX_PLAYERS, MIN_PLAYERS, Game, Phase
from bot.engine.roles import ROLES, Role, Team, register_custom

# Спеціальні ролі в порядку появи (кожна — з певної кількості гравців, див. roles.py).
VILLAGE_SPECIALS = ["znaharka", "harakternyk", "kum", "storozh", "kobzar", "otaman"]
SOLO_ROLES = ["duren", "vovkulaka"]


def evil_count(n: int) -> int:
    return max(1, round(n / 3.5))


def build_roles(n: int, disabled: Iterable[str] = (), custom: Iterable[Role] = ()) -> list[str]:
    """Повертає список ролей довжини n (ще не перемішаний).

    Свої ролі чату з'являються раніше за стандартні спецролі своєї сторони.
    """

    if not MIN_PLAYERS <= n <= MAX_PLAYERS:
        raise ValueError(f"players must be in {MIN_PLAYERS}..{MAX_PLAYERS}")
    off = {k for k in disabled if ROLES.get(k) and ROLES[k].optional}

    def enabled(key: str) -> bool:
        return key not in off and n >= ROLES[key].min_players

    custom = [r for r in custom if n >= r.min_players]
    evil = evil_count(n)
    roles = ["vidma"]
    for r in custom:
        if r.team == Team.EVIL and len(roles) < evil:
            roles.append(r.key)
    if len(roles) < evil and enabled("mavka"):
        roles.append("mavka")
    roles += ["upyr"] * (evil - len(roles))

    village_custom = [r.key for r in custom if r.team == Team.VILLAGE]
    for key in SOLO_ROLES + village_custom + VILLAGE_SPECIALS:
        if len(roles) >= n:
            break
        if key in village_custom or enabled(key):
            roles.append(key)
    roles += ["selianyn"] * (n - len(roles))
    return roles


def assign_roles(game: Game, rng: random.Random | None = None) -> None:
    rng = rng or random.Random()
    ids = list(game.players)
    custom = register_custom(game.settings.get("custom_roles", []))
    roles = build_roles(len(ids), game.settings.get("disabled_roles", ()), custom)
    rng.shuffle(roles)
    for uid, role in zip(ids, roles, strict=True):
        p = game.players[uid]
        p.role = role
        p.alive = True
        p.flags = {}
    game.phase = Phase.NIGHT
    game.day = 1
