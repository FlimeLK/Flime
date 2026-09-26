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
