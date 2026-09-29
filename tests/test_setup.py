import random
from collections import Counter

import pytest

from bot.engine.models import MAX_PLAYERS, MIN_PLAYERS, Game, Player
from bot.engine.roles import ROLES, Team
from bot.engine.setup import assign_roles, build_roles, evil_count


@pytest.mark.parametrize("n", range(MIN_PLAYERS, MAX_PLAYERS + 1))
def test_build_roles_counts(n):
    roles = build_roles(n)
    assert len(roles) == n
    c = Counter(roles)
    assert c["vidma"] == 1
    evil = sum(1 for r in roles if ROLES[r].team == Team.EVIL)
    assert evil == evil_count(n)
    # Нечисть завжди в меншості на старті.
    assert evil < n - evil
    for key, count in c.items():
        if key not in ("selianyn", "upyr"):
            assert count == 1, key
        assert n >= ROLES[key].min_players


def test_min_players_roles():
    assert sorted(build_roles(4)) == sorted(["vidma", "znaharka", "selianyn", "selianyn"])
    assert "vovkulaka" not in build_roles(9)
    assert "vovkulaka" in build_roles(10)


def test_disabled_roles_are_skipped_but_required_stay():
    roles = build_roles(12, disabled={"znaharka", "mavka", "vidma", "selianyn"})
    assert "znaharka" not in roles
    assert "mavka" not in roles
    assert "vidma" in roles
    assert len(roles) == 12


def test_assign_roles_sets_everyone():
    g = Game(chat_id=1)
    for i in range(1, 9):
        g.players[i] = Player(i, f"P{i}")
    assign_roles(g, random.Random(1))
    assert all(p.role for p in g.players.values())
    assert g.day == 1


def test_bad_player_count():
    with pytest.raises(ValueError):
        build_roles(3)


def _custom(i: int, team: str, ability: str, min_players: int = 4) -> dict:
    return {"id": 9000 + i, "name": f"Роль{i}", "emoji": "🦉", "emoji_id": None, "description": "опис",
            "team": team, "ability": ability, "min_players": min_players}


@pytest.mark.parametrize("n", range(MIN_PLAYERS, MAX_PLAYERS + 1))
def test_build_roles_with_custom(n):
    from bot.engine.roles import register_custom

    keys = register_custom([_custom(1, "evil", "block"), _custom(2, "village", "kill"),
                            _custom(3, "wolf", "none", min_players=8)])
    roles = build_roles(n, custom=keys)
    assert len(roles) == n
    evil = sum(1 for r in roles if ROLES[r].team == Team.EVIL)
    assert evil == evil_count(n) and evil < n - evil
    assert "c9002" in roles  # громада-вбивця з 4 гравців
    assert ("c9003" in roles) == (n >= 8)
    if evil_count(n) >= 2:
        assert "c9001" in roles


def test_custom_role_abilities():
    from bot.engine.roles import NightKind, register_custom

    k_evil, k_vill = register_custom([_custom(11, "evil", "kill"), _custom(12, "village", "kill")])
    assert ROLES[k_evil].night == (NightKind.KILL,)
    assert ROLES[k_vill].night == (NightKind.CUSTOM_KILL,)
    assert ROLES[k_vill].custom and ROLES[k_vill].team == Team.VILLAGE


def test_mafia_ratio():
    from bot.engine.setup import build_roles, evil_count

    assert evil_count(20, "few") < evil_count(20, "normal") < evil_count(20, "many")
    evil = {"vidma", "upyr", "mavka"}
    for ratio in ("few", "normal", "many"):
        for n in range(4, 31):
            roles = build_roles(n, ratio=ratio)
            assert len(roles) == n
            assert sum(r in evil for r in roles) == evil_count(n, ratio)
            assert sum(r in evil for r in roles) < n / 2
