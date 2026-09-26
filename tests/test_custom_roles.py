from collections import Counter

from bot.engine.models import Action, Game, Player
from bot.engine.night import can_target, resolve_night
from bot.engine.roles import NightKind as K
from bot.engine.roles import Team, register_custom, role
from bot.engine.setup import build_roles, evil_count
from bot.engine.voting import vote_weight


def custom(key: str, team: str, ability: str, min_players: int = 4) -> dict:
    return {"key": key, "name": key.upper(), "team": team, "ability": ability,
            "min_players": min_players, "description": ""}


def game_with(roles: list[str], customs: list[dict]) -> Game:
    g = Game(chat_id=-1, settings={"custom_roles": customs})
    register_custom(customs)
    for i, r in enumerate(roles, start=1):
        g.players[i] = Player(user_id=i, name=f"P{i}", role=r)
    g.day = 1
    return g


def test_custom_abilities_map_to_engine():
    healer, evil_killer, shooter, lucky, voter = register_custom([
        custom("c1", "village", "heal"), custom("c2", "evil", "kill"), custom("c3", "village", "kill"),
        custom("c4", "village", "lucky"), custom("c5", "village", "vote2"),
    ])
    assert healer.night == (K.HEAL,) and healer.team == Team.VILLAGE and healer.custom
    assert evil_killer.night == (K.KILL,) and evil_killer.team == Team.EVIL
    assert shooter.night == (K.SABER,)
    assert lucky.passives == ("lucky",) and voter.passives == ("vote2",)
    assert role("c1") is healer


def test_build_roles_puts_custom_first():
    customs = register_custom([custom("c10", "village", "check"), custom("c11", "evil", "block"),
                               custom("c12", "village", "none", min_players=12)])
    roles = build_roles(8, custom=customs)
    c = Counter(roles)
    assert c["c10"] == 1 and c["c11"] == 1 and "c12" not in c
    assert sum(1 for r in roles if role(r).team == Team.EVIL) == evil_count(8)
    assert "c12" in build_roles(12, custom=customs)


def test_custom_roles_work_at_night():
    customs = [custom("c20", "evil", "kill"), custom("c21", "village", "kill"),
               custom("c22", "village", "lucky"), custom("c23", "village", "vote2")]
    g = game_with(["vidma", "c20", "c21", "c22", "c23", "selianyn"], customs)
    assert [p.user_id for p in g.evil_voters()] == [1, 2]

    # Нечисть б'є «везунчика» — він виживає; свій стрілець з Громади вбиває раз за гру.
    g.evil_votes = {1: 4, 2: 4}
    g.actions["3:role"] = Action(3, K.SABER, 6)
    r = resolve_night(g)
    assert r.saved == [(4, "lucky")] and r.deaths == [(6, "shot")]
    assert K.SABER not in g.night_kinds(g.players[3])
    assert vote_weight(g, 5) == 2


def test_custom_blocker_from_village_can_block_evil():
    customs = [custom("c30", "village", "block")]
    g = game_with(["vidma", "c30", "selianyn", "selianyn"], customs)
    assert can_target(g, 2, K.LURE, 1)
    g.actions["2:role"] = Action(2, K.LURE, 1)
    g.evil_votes = {1: 3}
    assert resolve_night(g).deaths == []


def test_snapshot_restores_custom_roles():
    from bot.engine.roles import CUSTOM_ROLES

    g = game_with(["vidma", "c40", "selianyn", "selianyn"], [custom("c40", "village", "watch")])
    data = g.to_dict()
    CUSTOM_ROLES.pop("c40")
    restored = Game.from_dict(data)
    assert restored.players[2].role_obj.night == (K.WATCH,)
