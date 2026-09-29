"""Випадкові повні ігри: різна кількість гравців, предмети, власні ролі, випадкові дії й голоси.
Жодна гра не повинна впасти чи зависнути."""

from __future__ import annotations

import asyncio
import random

import pytest

from bot import texts
from bot.db import shop as shop_db
from bot.db import users as users_db
from bot.db.groups import GroupSettings
from bot.engine.items import ITEMS, POCKET_ORDER
from bot.engine.models import Game, Phase
from bot.engine.night import can_target
from bot.engine.roles import ABILITIES
from bot.game.runner import ITEM_SLOT, GameRunner
from tests.test_flow import FakeMessenger, wait_phase

TEAMS = ("village", "evil", "wolf")


def _custom(rng: random.Random, base: int) -> list[dict]:
    return [
        {"id": base + i, "name": f"Кастом{i}", "emoji": "🙂", "emoji_id": None, "description": "d",
         "team": rng.choice(TEAMS), "ability": rng.choice(list(ABILITIES)), "min_players": rng.randint(4, 8)}
        for i in range(rng.randint(0, 3))
    ]


def _act(runner: GameRunner, rng: random.Random) -> None:
    g = runner.game
    for uid, slot in list(runner._pending):
        if rng.random() < 0.15:
            continue  # гравець проспав
        if slot == ITEM_SLOT:
            runner.night_action(uid, "pitchfork", rng.choice([0, *g.alive_ids()]))
            continue
        p = g.players[uid]
        for kind in g.night_kinds(p):
            targets = [t for t in g.alive_ids() if can_target(g, uid, kind, t)]
            if not targets:
                continue
            first = rng.choice(targets)
            runner.night_action(uid, kind.value, first)
            if kind.value == "compare":
                rest = [t for t in g.alive_ids() if t not in (uid, first)]
                if rest:
                    runner.night_action(uid, "compare2", rng.choice(rest))
            break


@pytest.mark.parametrize("seed", range(12))
async def test_random_game(pool, seed):
    rng = random.Random(seed)
    n = rng.randint(4, 14)
    ids = [seed * 100 + i + 10_000 for i in range(n)]
    for uid in ids:
        await users_db.upsert(pool, uid, f"P{uid}", None)
        for item in rng.sample(POCKET_ORDER, rng.randint(0, 3)):
            await shop_db.add_item(pool, uid, item, 1)
    chat = -(seed + 7000)
    s = GroupSettings(chat_id=chat, night_time=1, day_time=0, vote_time=1, confirm_time=1,
                      hide_dead_roles=rng.random() < 0.5, secret_vote=rng.random() < 0.5,
                      items_enabled=rng.random() < 0.8, mafia_ratio=rng.choice(["few", "normal", "many"]),
                      disabled_items=rng.sample(list(ITEMS), rng.randint(0, 3)),
                      pin_lobby=rng.random() < 0.5, omerta_dead=rng.random() < 0.5)
    game = Game(chat_id=chat, settings={**s.to_dict(), "custom_roles": _custom(rng, seed * 10 + 50_000)},
                starter_id=ids[0])
    m = FakeMessenger()
    finished = asyncio.Event()
    runner = GameRunner(game, m, pool, "test_bot", lambda _c: finished.set(), chat_title="T")
    runner.start()
    await wait_phase(runner, Phase.LOBBY)
    await asyncio.sleep(0.02)
    for uid in ids:
        runner.join(uid, f"P{uid}", vip=rng.random() < 0.3)
    assert runner.force_start()
    for _ in range(80):
        await wait_phase(runner, Phase.NIGHT, Phase.VOTE, Phase.CONFIRM, Phase.FINISHED, timeout=10)
        if game.phase == Phase.FINISHED:
            break
        await asyncio.sleep(0.03)
        if game.phase == Phase.NIGHT:
            _act(runner, rng)
            await wait_phase(runner, Phase.DAY, Phase.VOTE, Phase.FINISHED, timeout=10)
        elif game.phase == Phase.VOTE:
            for p in game.alive():
                if rng.random() < 0.9:
                    runner.vote(p.user_id, rng.choice([0, *[x for x in game.alive_ids() if x != p.user_id]]))
            await wait_phase(runner, Phase.CONFIRM, Phase.NIGHT, Phase.FINISHED, timeout=10)
        elif game.phase == Phase.CONFIRM:
            for p in game.alive():
                runner.confirm_vote(p.user_id, rng.random() < 0.7)
            await wait_phase(runner, Phase.NIGHT, Phase.FINISHED, timeout=10)
    await asyncio.wait_for(finished.wait(), 10)
    assert game.phase == Phase.FINISHED
    assert not any(t == texts.GAME_CRASHED for _, t in m.sent)
    for p in game.players.values():
        assert not set(p.pocket) & set(s.disabled_items)
