from bot.engine.models import Action, Game
from bot.engine.night import can_target, resolve_night
from bot.engine.roles import NightKind as K

from .helpers import make_game

# Розстановка за замовчуванням:
# 1 Дон, 2 Мафія, 3 Коханка, 4 Лікар, 5 Комісар, 6 Щасливчик, 7 Волоцюга, 8 Журналіст, 9 Мирний, 10 Маніяк
ROLES = ["vidma", "upyr", "mavka", "znaharka", "harakternyk", "kum", "storozh", "kobzar", "selianyn", "vovkulaka"]


def act(g: Game, actor: int, kind: K, target: int, target2: int | None = None, slot: str = "role"):
    g.actions[f"{actor}:{slot}"] = Action(actor, kind, target, target2)


def test_evil_kill():
    g = make_game(ROLES)
    g.evil_votes = {1: 9, 2: 9}
    r = resolve_night(g)
    assert r.deaths == [(9, "evil")]
    assert not g.players[9].alive


def test_leader_decides_over_majority():
    g = make_game(ROLES)
    g.evil_votes = {1: 9, 2: 7}
    r = resolve_night(g)
    assert r.deaths == [(9, "evil")]


def test_upyr_tie_without_leader_no_kill():
    # Ватажок (перший упир) не голосував, двоє інших не домовились.
    g = make_game(["upyr", "upyr", "upyr", "selianyn", "selianyn", "selianyn", "selianyn", "selianyn"])
    g.evil_votes = {2: 4, 3: 5}
    assert resolve_night(g).deaths == []


def test_upyr_leads_when_witch_dead():
    g = make_game(ROLES)
    g.players[1].alive = False
    g.evil_votes = {2: 9}
    assert resolve_night(g).deaths == [(9, "evil")]


def test_healer_saves():
    g = make_game(ROLES)
    g.evil_votes = {1: 9}
    act(g, 4, K.HEAL, 9)
    r = resolve_night(g)
    assert r.deaths == []
    assert r.saved == [(9, "heal")]
    assert g.players[4].flags["last_heal"] == 9


def test_mavka_blocks_healer():
    g = make_game(ROLES)
    g.evil_votes = {1: 9}
    act(g, 4, K.HEAL, 9)
    act(g, 3, K.LURE, 4)
    r = resolve_night(g)
    assert r.lured == [4]
    assert r.deaths == [(9, "evil")]


def test_garlic_protects_from_mavka():
    g = make_game(ROLES, pockets={4: ["garlic"]})
    g.evil_votes = {1: 9}
    act(g, 4, K.HEAL, 9)
    act(g, 3, K.LURE, 4)
    r = resolve_night(g)
    assert r.garlic == [4]
    assert r.lured == []
    assert r.deaths == []
    assert g.players[4].pocket == []


def test_obereg_and_kum():
    g = make_game(ROLES, pockets={9: ["obereg"]})
    g.evil_votes = {1: 9}
    act(g, 10, K.WOLF_KILL, 6)
    r = resolve_night(g)
    assert sorted(r.saved) == [(6, "kum"), (9, "obereg")]
    assert r.deaths == []
    # Вдруге кум не везе
    g.actions.clear()
    g.evil_votes = {1: 6}
    assert resolve_night(g).deaths == [(6, "evil")]


def test_check_and_mask():
    g = make_game(ROLES, pockets={2: ["mask"]})
    act(g, 5, K.CHECK, 1)
    assert resolve_night(g).checks[5] == (1, False)
    g.actions.clear()
    act(g, 5, K.CHECK, 2)
    assert resolve_night(g).checks[5] == (2, True)
    assert g.players[2].pocket == []
    g.actions.clear()
    act(g, 5, K.CHECK, 9)
    assert resolve_night(g).checks[5] == (9, True)


def test_saber_once():
    g = make_game(ROLES)
    act(g, 5, K.SABER, 10)
    assert resolve_night(g).deaths == [(10, "saber")]
    assert g.players[5].flags["saber_used"]
    assert K.SABER not in g.night_kinds(g.players[5])


def test_pitchfork_item_action():
    g = make_game(ROLES, pockets={9: ["pitchfork"]})
    assert K.PITCHFORK in g.night_kinds(g.players[9])
    act(g, 9, K.PITCHFORK, 1, slot="item")
    r = resolve_night(g)
    assert r.deaths == [(1, "pitchfork")]
    assert g.players[9].pocket == []


def test_watch_and_candle():
    g = make_game(ROLES, pockets={9: ["candle"]})
    g.evil_votes = {1: 9}
    act(g, 4, K.HEAL, 9)
    act(g, 7, K.WATCH, 9)
    r = resolve_night(g)
    assert sorted(r.watches[7][1]) == [1, 4]
    assert sorted(r.candles[9]) == [1, 4, 7]


def test_compare():
    g = make_game(ROLES)
    act(g, 8, K.COMPARE, 1, 2)
    assert resolve_night(g).compares[8] == (1, 2, True)
    g.actions.clear()
    act(g, 8, K.COMPARE, 1, 9)
    assert resolve_night(g).compares[8] == (1, 9, False)


def test_dead_actor_does_nothing():
    g = make_game(ROLES)
    g.players[10].alive = False
    act(g, 10, K.WOLF_KILL, 9)
    assert resolve_night(g).deaths == []


def test_can_target_rules():
    g = make_game(ROLES)
    assert not can_target(g, 1, K.KILL, 2)        # не свого
    assert can_target(g, 1, K.KILL, 9)
    assert not can_target(g, 3, K.LURE, 3)
    assert can_target(g, 4, K.HEAL, 4)
    g.players[4].flags["self_healed"] = True
    assert not can_target(g, 4, K.HEAL, 4)
    g.players[4].flags["last_heal"] = 9
    assert not can_target(g, 4, K.HEAL, 9)
    assert not can_target(g, 9, K.PITCHFORK, 1)   # немає вил
    assert not can_target(g, 9, K.HEAL, 1)        # не його роль


def test_heal_same_target_allowed_after_skip_night():
    g = make_game(ROLES)
    act(g, 4, K.HEAL, 9)
    resolve_night(g)
    g.actions.clear()
    resolve_night(g)  # знахарка пропустила ніч
    assert can_target(g, 4, K.HEAL, 9)


def test_lone_mavka_becomes_killer():
    g = make_game(ROLES)
    g.players[1].alive = False
    g.players[2].alive = False
    assert g.night_kinds(g.players[3]) == [K.KILL]
    assert g.evil_leader().user_id == 3
    assert can_target(g, 3, K.KILL, 9)
    g.evil_votes = {3: 9}
    assert resolve_night(g).deaths == [(9, "evil")]


def test_custom_village_killer_and_blocker():
    from bot.engine.roles import register_custom

    killer, blocker = register_custom([
        {"id": 8001, "name": "Мисливець", "emoji": "🏹", "team": "village", "ability": "kill", "min_players": 4},
        {"id": 8002, "name": "Сторожиха", "emoji": "🧹", "team": "village", "ability": "block", "min_players": 4},
    ])
    g = make_game(["vidma", "znaharka", killer, blocker, "selianyn", "selianyn"])
    assert can_target(g, 3, K.CUSTOM_KILL, 1)
    assert can_target(g, 4, K.LURE, 1)  # блокувальник з Громади може зупинити відьму
    act(g, 3, K.CUSTOM_KILL, 5)
    act(g, 4, K.LURE, 1)
    g.evil_votes = {1: 6}
    r = resolve_night(g)
    assert r.lured == [1]
    assert r.deaths == [(5, "custom")]  # відьму затримали - її жертва жива
