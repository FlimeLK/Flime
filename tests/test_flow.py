"""Наскрізна симуляція гри: GameRunner + справжня PostgreSQL + фейковий Telegram.

Потрібна тестова база: HUTIR_TEST_DSN (за замовчуванням локальна hutir_test).
Без бази тест пропускається.
"""

from __future__ import annotations

import asyncio

from bot.db import games as games_db
from bot.db import shop as shop_db
from bot.db import users as users_db
from bot.db.groups import GroupSettings
from bot.engine.models import Phase
from bot.engine.night import can_target
from bot.engine.roles import NightKind, Team
from bot.game.runner import ITEM_SLOT, ROLE_SLOT, GameRunner

from .conftest import DSN  # noqa: F401


class FakeMessenger:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self._id = 0

    async def send(self, chat_id, text, markup=None):
        self._id += 1
        self.sent.append((chat_id, text))
        return self._id

    async def edit(self, chat_id, message_id, text, markup=None):
        pass

    async def clear_markup(self, chat_id, message_id):
        pass


async def wait_phase(runner: GameRunner, *phases: Phase, timeout: float = 5) -> None:
    for _ in range(int(timeout / 0.01)):
        if runner.game.phase in phases:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"phase {runner.game.phase} not in {phases}")


def play_night(runner: GameRunner) -> None:
    g = runner.game
    for (uid, slot) in list(runner._pending):
        if slot == ITEM_SLOT:
            runner.night_action(uid, NightKind.PITCHFORK.value, 0)
            continue
        p = g.players[uid]
        kind = p.role_obj.night[0]
        targets = [t for t in g.alive_ids() if can_target(g, uid, kind, t)]
        if kind == NightKind.COMPARE:
            runner.night_action(uid, kind.value, targets[0])
            second = next(t for t in g.alive_ids() if t not in (uid, targets[0]))
            runner.night_action(uid, "compare2", second)
        else:
            runner.night_action(uid, kind.value, targets[-1])
    assert not runner._pending or all(s == ROLE_SLOT for _, s in runner._pending)


def play_vote(runner: GameRunner) -> None:
    g = runner.game
    # Громада дружно голосує за першого живого з нечисті.
    evil = [p.user_id for p in g.alive() if p.team in (Team.EVIL, Team.WOLF)]
    for p in g.alive():
        target = next((e for e in evil if e != p.user_id), 0)
        runner.vote(p.user_id, target)


async def test_full_game(pool):
    ids = list(range(1001, 1009))
    for uid in ids:
        await users_db.upsert(pool, uid, f"Гравець{uid}", None)
    await shop_db.add_item(pool, ids[0], "obereg", 2)

    finished = asyncio.Event()
    settings = GroupSettings(chat_id=-500, night_time=2, day_time=0, vote_time=2, confirm_time=2)
    from bot.engine.models import Game

    game = Game(chat_id=-500, settings=settings.to_dict(), starter_id=ids[0])
    m = FakeMessenger()
    runner = GameRunner(game, m, pool, "test_bot", lambda _chat: finished.set(), chat_title="Тест")
    runner.start()
    await wait_phase(runner, Phase.LOBBY)
    await asyncio.sleep(0.05)
    assert not runner.force_start()  # ще нікого
    for uid in ids:
        assert runner.join(uid, f"Гравець{uid}", vip=False) is None
    assert runner.join(ids[0], "x", vip=False) is not None
    assert runner.force_start()

    await wait_phase(runner, Phase.NIGHT)
    assert game.players[ids[0]].pocket == ["obereg"]
    assert all(p.role for p in game.players.values())

    for _ in range(20):
        await wait_phase(runner, Phase.NIGHT, Phase.VOTE, Phase.CONFIRM, Phase.FINISHED)
        if game.phase == Phase.FINISHED:
            break
        await asyncio.sleep(0.05)  # даємо розіслати підказки
        if game.phase == Phase.NIGHT:
            play_night(runner)
            await wait_phase(runner, Phase.DAY, Phase.VOTE, Phase.FINISHED)
        elif game.phase == Phase.VOTE:
            play_vote(runner)
            await wait_phase(runner, Phase.CONFIRM, Phase.NIGHT, Phase.FINISHED)
        elif game.phase == Phase.CONFIRM:
            for p in game.alive():
                if p.user_id != game.candidate:
                    runner.confirm_vote(p.user_id, True)
            await wait_phase(runner, Phase.NIGHT, Phase.FINISHED)

    await asyncio.wait_for(finished.wait(), 5)
    assert game.phase == Phase.FINISHED and game.winner
    assert await games_db.load_snapshots(pool) == []
    res = await pool.fetchrow("SELECT * FROM game_results WHERE chat_id = -500")
    assert res["players"] == 8
    u = await users_db.get(pool, ids[1])
    assert u.games == 1 and u.shagy > 100
    assert any("Гру завершено" in text for _, text in m.sent)


async def test_stop_returns_items(pool):
    ids = list(range(2001, 2006))
    for uid in ids:
        await users_db.upsert(pool, uid, f"P{uid}", None)
    await shop_db.add_item(pool, ids[0], "honey", 1)
    from bot.engine.models import Game

    finished = asyncio.Event()
    game = Game(chat_id=-600, settings=GroupSettings(chat_id=-600, night_time=30).to_dict())
    runner = GameRunner(game, FakeMessenger(), pool, "test_bot", lambda _c: finished.set())
    runner.start()
    await wait_phase(runner, Phase.LOBBY)
    await asyncio.sleep(0.05)
    for uid in ids:
        runner.join(uid, f"P{uid}", vip=False)
    runner.force_start()
    await wait_phase(runner, Phase.NIGHT)
    await asyncio.sleep(0.05)
    assert await shop_db.inventory(pool, ids[0]) == {}
    await runner.stop()
    assert finished.is_set()
    assert await shop_db.inventory(pool, ids[0]) == {"honey": 1}
    assert await games_db.load_snapshots(pool) == []
