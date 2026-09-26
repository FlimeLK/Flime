from bot.engine.models import Game
from bot.engine.roles import Team
from bot.engine.voting import SKIP, confirm_result, lynch, tally, use_honey
from bot.engine.win import DRAW, check_winner, winners

from .helpers import make_game


def test_tally_majority_tie_skip():
    g = make_game(["vidma", "selianyn", "selianyn", "selianyn", "selianyn"])
    g.votes = {1: 2, 2: 1, 3: 1, 4: 1}
    assert tally(g)[0] == 1
    g.votes = {1: 2, 2: 1}
    assert tally(g)[0] is None  # нічия
    g.votes = {1: 2, 3: SKIP, 4: SKIP}
    assert tally(g)[0] is None  # більшість пропускає
    g.votes = {}
    assert tally(g)[0] is None


def test_otaman_and_honey_double_votes():
    g = make_game(["vidma", "otaman", "selianyn", "selianyn"], pockets={3: ["honey"]})
    g.votes = {2: 1, 1: 3, 4: 3}
    assert tally(g)[0] is None  # 2 проти 2
    assert use_honey(g, 3)
    assert not use_honey(g, 3)
    g.votes[3] = 1
    assert tally(g)[0] == 1  # 2 + 2 проти 2


def test_confirm_excludes_candidate():
    g = make_game(["vidma", "selianyn", "selianyn", "selianyn"])
    g.candidate = 1
    g.confirm = {1: False, 2: True, 3: False, 4: True}
    assert confirm_result(g) == (True, 2, 1)
    g.confirm = {2: True, 3: False}
    assert confirm_result(g)[0] is False


def test_lynch_horseshoe_and_fool():
    g = make_game(["vidma", "duren", "selianyn", "selianyn", "selianyn"], pockets={3: ["horseshoe"]})
    r = lynch(g, 3)
    assert r.horseshoe and not r.died and g.players[3].alive
    r = lynch(g, 2)
    assert r.fool and g.fool_won and not g.players[2].alive


def _kill(g: Game, *ids: int):
    for i in ids:
        g.players[i].alive = False


def test_win_conditions():
    g = make_game(["vidma", "upyr", "selianyn", "selianyn", "selianyn", "selianyn"])
    assert check_winner(g) is None
    _kill(g, 1, 2)
    assert check_winner(g) == Team.VILLAGE

    g = make_game(["vidma", "upyr", "selianyn", "selianyn", "selianyn", "selianyn"])
    _kill(g, 3, 4)
    assert check_winner(g) == Team.EVIL

    g = make_game(["vidma", "vovkulaka", "selianyn", "selianyn"])
    _kill(g, 1)
    assert check_winner(g) is None
    _kill(g, 3)
    assert check_winner(g) == Team.WOLF

    g = make_game(["vidma", "selianyn"])
    _kill(g, 1, 2)
    assert check_winner(g) == DRAW


def test_winners_include_dead_teammates_and_fool():
    g = make_game(["vidma", "duren", "selianyn", "selianyn"])
    lynch(g, 2)
    _kill(g, 1)
    w = check_winner(g)
    assert w == Team.VILLAGE
    assert winners(g, w) == {2, 3, 4}


def test_serialization_roundtrip():
    g = make_game(["vidma", "znaharka", "selianyn", "selianyn"], pockets={3: ["candle"]})
    g.evil_votes = {1: 3}
    g.votes = {2: 1}
    g.players[2].flags["last_heal"] = 3
    g2 = Game.from_dict(g.to_dict())
    assert g2.to_dict() == g.to_dict()
    assert g2.evil_votes == {1: 3}
