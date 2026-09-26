"""Ведучий однієї гри: фази, таймери, повідомлення.

Вся зміна стану в обробниках кнопок відбувається синхронно (без await
посередині), тому окремий замок не потрібен: asyncio однопотоковий.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncpg
from aiogram.types import InlineKeyboardMarkup

from bot import economy, texts
from bot.db import custom_roles as custom_roles_db
from bot.db import games as games_db
from bot.db import shop as shop_db
from bot.engine import items as it
from bot.engine.models import BOT_NAMES, MAX_PLAYERS, MIN_PLAYERS, Action, Game, Phase, Player, is_bot_player
from bot.engine.night import can_target, resolve_night
from bot.engine.roles import TEAM_TITLES, NightKind, Team
from bot.engine.setup import assign_roles
from bot.engine.voting import (
    SKIP,
    can_vote,
    confirm_decided,
    confirm_result,
    lynch,
    tally,
    use_honey,
    vote_decided,
)
from bot.engine.win import check_winner, winners
from bot.game import views
from bot.game.messenger import Messenger

log = logging.getLogger(__name__)

ROLE_SLOT = "role"
ITEM_SLOT = "item"


@dataclass
class Reply:
    """Відповідь обробнику кнопки: або спливне повідомлення, або нове тексту/клавіатура."""

    text: str
    alert: bool = False
    markup: InlineKeyboardMarkup | None = None


class GameRunner:
    def __init__(
        self,
        game: Game,
        messenger: Messenger,
        pool: asyncpg.Pool,
        bot_username: str,
        on_finish: Callable[[int], Awaitable[None] | None],
        chat_title: str = "",
    ):
        self.game = game
        self.m = messenger
        self.pool = pool
        self.bot_username = bot_username
        self.chat_title = chat_title
        self._on_finish = on_finish
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._force_start = False
        self._stopped = False
        self._deadline = 0.0
        # Нічні/голосувальні підказки: (uid, slot) → message_id-и, які ще чекають відповіді.
        self._pending: dict[tuple[int, str], list[int]] = {}
        self._compare_first: dict[int, int] = {}
        self._confirm_mid: int | None = None
        self._background: set[asyncio.Task] = set()
        # Пауза перед голосом бота тестової гри (секунди, від–до), щоб голоси йшли природно.
        self.bot_delay: tuple[float, float] = (1.0, 4.0)
        self._bot_tasks: set[asyncio.Task] = set()
        # Живі повідомлення (лобі, суд): message_id → чи треба ще раз оновити.
        self._live_dirty: dict[int, bool] = {}
        self._confirm_open = False

    def _bg(self, coro: Awaitable) -> None:
        task = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _live_edit(self, message_id: int | None, render: Callable[[], tuple[str, InlineKeyboardMarkup | None]]) -> None:
        """Оновлює «живе» повідомлення: по одному редагуванню за раз і завжди з останнім станом.

        Паралельні edit-и доходять до Telegram у довільному порядку, тож лічильники «стрибали» б.
        """
        if not message_id:
            return
        if message_id in self._live_dirty:
            self._live_dirty[message_id] = True
            return
        self._live_dirty[message_id] = False

        async def run() -> None:
            try:
                while True:
                    text, markup = render()
                    await self.m.edit(self.chat_id, message_id, text, markup)
                    if not self._live_dirty.get(message_id):
                        return
                    self._live_dirty[message_id] = False
            finally:
                self._live_dirty.pop(message_id, None)

        self._bg(run())

    async def _flush(self) -> None:
        """Чекаємо фонові надсилання, щоб підсумки не випереджали оголошення голосів."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    def _bot_later(self, action: Callable[[], object]) -> None:
        """Хід бота з невеликою паузою; скасовується, коли фаза закінчується."""
        async def run() -> None:
            await asyncio.sleep(random.uniform(*self.bot_delay))
            action()

        task = asyncio.ensure_future(run())
        self._bot_tasks.add(task)
        task.add_done_callback(self._bot_tasks.discard)

    def _cancel_bot_moves(self) -> None:
        for task in list(self._bot_tasks):
            task.cancel()

    @property
    def chat_id(self) -> int:
        return self.game.chat_id

    # ================= життєвий цикл =================

    def start(self, resumed: bool = False) -> None:
        self._task = asyncio.create_task(self._run(resumed))

    async def _run(self, resumed: bool) -> None:
        cleanup = False
        try:
            if resumed:
                await self.m.send(self.chat_id, texts.GAME_RESUMED)
            phases = {
                Phase.LOBBY: self._lobby,
                Phase.NIGHT: self._night,
                Phase.DAY: self._day,
                Phase.VOTE: self._vote,
                Phase.CONFIRM: self._confirm,
            }
            while self.game.phase != Phase.FINISHED:
                await games_db.save_snapshot(self.pool, self.chat_id, self.game.to_dict())
                await phases[self.game.phase]()
            cleanup = True
        except asyncio.CancelledError:
            # Зупинка адміном — прибираємо; вимкнення бота — лишаємо снапшот для відновлення.
            cleanup = self._stopped
            raise
        except Exception:
            log.exception("Game in chat %s crashed", self.chat_id)
            cleanup = True
            await self._return_pockets()
            await self.m.send(self.chat_id, texts.GAME_CRASHED)
        finally:
            if cleanup:
                try:
                    await games_db.delete_snapshot(self.pool, self.chat_id)
                finally:
                    res = self._on_finish(self.chat_id)
                    if asyncio.iscoroutine(res):
                        await res

    async def stop(self) -> None:
        self._stopped = True
        self._cancel_bot_moves()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._clear_pending(texts.NIGHT_NOT_NOW)
        await self._return_pockets()
        await self.m.send(self.chat_id, texts.GAME_STOPPED)

    async def shutdown(self) -> None:
        """Зупинка без прибирання (бот вимикається, гру відновимо після старту)."""
        self._cancel_bot_moves()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _wait(self, seconds: float, done: Callable[[], bool] = lambda: False) -> None:
        loop = asyncio.get_running_loop()
        self._deadline = loop.time() + seconds
        while not done():
            remaining = self._deadline - loop.time()
            if remaining <= 0:
                return
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=remaining)
            except TimeoutError:
                return

    def _poke(self) -> None:
        self._wake.set()

    def remaining(self) -> int:
        return max(0, int(self._deadline - asyncio.get_running_loop().time()))

    # ================= лобі =================

    def join(self, user_id: int, name: str, vip: bool) -> str | None:
        """Повертає None при успіху або текст помилки."""
        g = self.game
        if g.phase != Phase.LOBBY:
            return texts.JOIN_CLOSED
        if user_id in g.players:
            return texts.JOIN_ALREADY_HERE
        if len(g.players) >= MAX_PLAYERS:
            return texts.JOIN_FULL.format(max=MAX_PLAYERS)
        g.players[user_id] = Player(user_id=user_id, name=name, vip=vip)
        return None

    @property
    def is_test(self) -> bool:
        return bool(self.game.settings.get("test_game"))

    def add_bots(self, count: int) -> int:
        """Додає ботів у набір тестової гри. Повертає, скільки додано."""
        g = self.game
        added = 0
        for i in range(1, 100):
            if added >= count or len(g.players) >= MAX_PLAYERS:
                break
            uid = -i
            if uid in g.players:
                continue
            g.players[uid] = Player(user_id=uid, name=BOT_NAMES[(i - 1) % len(BOT_NAMES)])
            added += 1
        return added

    def _bots(self) -> list[Player]:
        return [p for p in self.game.alive() if is_bot_player(p.user_id)]

    def _bots_night(self) -> None:
        """Боти тестової гри роблять нічні ходи випадково, але за правилами."""
        g = self.game
        for p in self._bots():
            for kind in g.night_kinds(p):
                if kind == NightKind.PITCHFORK or (kind == NightKind.SABER and random.random() < 0.7):
                    continue
                targets = [t.user_id for t in g.alive() if can_target(g, p.user_id, kind, t.user_id)]
                if not targets:
                    continue
                target = random.choice(targets)
                if kind == NightKind.KILL:
                    g.evil_votes[p.user_id] = target
                elif kind == NightKind.COMPARE:
                    others = [t.user_id for t in g.alive() if t.user_id not in (p.user_id, target)]
                    if others:
                        g.actions[f"{p.user_id}:{ROLE_SLOT}"] = Action(p.user_id, kind, target, random.choice(others))
                else:
                    g.actions[f"{p.user_id}:{ROLE_SLOT}"] = Action(p.user_id, kind, target)

    def leave(self, user_id: int) -> bool:
        if self.game.phase != Phase.LOBBY or user_id not in self.game.players:
            return False
        del self.game.players[user_id]
        return True

    def force_start(self) -> bool:
        if self.game.phase != Phase.LOBBY or len(self.game.players) < MIN_PLAYERS:
            return False
        self._force_start = True
        self._poke()
        return True

    def _lobby_text(self) -> str:
        players = [(p.user_id, p.name) for p in self.game.players.values()]
        return texts.lobby(players, self.remaining(), MIN_PLAYERS)

    async def refresh_lobby(self) -> None:
        if self.game.phase != Phase.LOBBY:
            return
        self._live_edit(self.game.lobby_message_id, lambda: (
            self._lobby_text(), views.join_keyboard(self.bot_username, self.chat_id)))

    async def _lobby(self) -> None:
        g = self.game
        total = int(g.settings.get("reg_time", 90))
        self._deadline = asyncio.get_running_loop().time() + total
        g.lobby_message_id = await self.m.send(
            self.chat_id, self._lobby_text(), views.join_keyboard(self.bot_username, self.chat_id)
        )
        started = lambda: self._force_start  # noqa: E731
        if total > 45:
            await self._wait(total - 30, started)
            if not self._force_start:
                await self.m.send(self.chat_id, texts.LOBBY_REMINDER.format(left=texts.fmt_seconds(30)))
                await self._wait(30, started)
        else:
            await self._wait(total, started)

        if g.lobby_message_id:
            await self._flush()
            await self.m.clear_markup(self.chat_id, g.lobby_message_id)
        if len(g.players) < MIN_PLAYERS:
            await self.m.send(self.chat_id, texts.LOBBY_NOT_ENOUGH.format(min=MIN_PLAYERS))
            g.phase = Phase.FINISHED
            return
        await self._start_game()

    async def _start_game(self) -> None:
        g = self.game
        customs = await custom_roles_db.list_for_chat(self.pool, self.chat_id)
        g.settings["custom_roles"] = [r.to_engine() for r in customs if r.enabled]
        assign_roles(g)
        if g.settings.get("items_enabled", True) and not self.is_test:
            for p in g.players.values():
                slots = it.VIP_POCKET_SLOTS if p.vip else it.BASE_POCKET_SLOTS
                p.pocket = await shop_db.take_for_game(self.pool, p.user_id, slots, it.POCKET_ORDER)

        teams = Counter(p.team for p in g.players.values())
        composition = "\n".join(f"{TEAM_TITLES[t]}: <b>{teams[t]}</b>" for t in Team if teams[t])
        await self.m.send(self.chat_id, texts.GAME_STARTED.format(n=len(g.players), composition=composition))

        evil = [p for p in g.players.values() if p.team == Team.EVIL]
        for p in g.players.values():
            allies = []
            if p.team == Team.EVIL:
                allies = [f"{texts.mention(a.user_id, a.name)} ({a.role_obj.title})" for a in evil if a is not p]
            await self.m.send(p.user_id, texts.role_card(p.role, p.pocket, allies))

    # ================= ніч =================

    async def _night(self) -> None:
        g = self.game
        g.actions.clear()
        g.evil_votes.clear()
        self._compare_first.clear()
        self._pending.clear()

        alive = [(p.user_id, p.name) for p in g.alive()]
        await self.m.send(self.chat_id, texts.night_start(g.day, alive), views.to_bot_keyboard(self.bot_username))

        for p in g.alive():
            if is_bot_player(p.user_id):
                continue  # боти ходять у _bots_night
            for kind in g.night_kinds(p):
                slot = ITEM_SLOT if kind == NightKind.PITCHFORK else ROLE_SLOT
                prompt = texts.NIGHT_PROMPTS["shot" if kind == NightKind.SABER and p.role_obj.custom else kind.value]
                mid = await self.m.send(p.user_id, prompt,
                                        views.night_targets(g, p.user_id, kind))
                if mid:
                    self._pending.setdefault((p.user_id, slot), []).append(mid)
        self._bots_night()

        await self._wait(int(g.settings.get("night_time", 60)), lambda: not self._pending)
        await self._clear_pending(texts.NIGHT_EXPIRED)
        await self._morning()

    def night_action(self, user_id: int, kind_raw: str, target: int) -> Reply:
        g = self.game
        if g.phase != Phase.NIGHT:
            return Reply(texts.NIGHT_NOT_NOW, alert=True)

        if kind_raw == "compare2":
            first = self._compare_first.get(user_id)
            if (user_id, ROLE_SLOT) not in self._pending or first is None:
                return Reply(texts.NIGHT_NOT_NOW, alert=True)
            if target in (user_id, first) or target not in g.players or not g.players[target].alive:
                return Reply(texts.NIGHT_BAD_TARGET, alert=True)
            g.actions[f"{user_id}:{ROLE_SLOT}"] = Action(user_id, NightKind.COMPARE, first, target)
            self._resolve_slot(user_id, ROLE_SLOT)
            names = f"{g.players[first].name} і {g.players[target].name}"
            return Reply(texts.NIGHT_CHOSEN.format(target=names))

        try:
            kind = NightKind(kind_raw)
        except ValueError:
            return Reply(texts.NIGHT_NOT_NOW, alert=True)
        slot = ITEM_SLOT if kind == NightKind.PITCHFORK else ROLE_SLOT
        if (user_id, slot) not in self._pending:
            return Reply(texts.NIGHT_NOT_NOW, alert=True)

        if target == 0:
            if kind == NightKind.PITCHFORK:
                self._resolve_slot(user_id, slot)
                return Reply(texts.NIGHT_CHOSEN.format(target="нікого"))
            if kind == NightKind.SABER:
                # Шаблю відклали — лишається перевірка.
                return Reply(texts.NIGHT_CHOSEN.format(target="шабля лишається в піхвах"))
            return Reply(texts.NIGHT_BAD_TARGET, alert=True)

        if not can_target(g, user_id, kind, target):
            return Reply(texts.NIGHT_BAD_TARGET, alert=True)
        target_name = g.players[target].name

        if kind == NightKind.COMPARE:
            self._compare_first[user_id] = target
            return Reply(texts.NIGHT_PROMPTS["compare2"].format(first=target_name),
                         markup=views.compare_second(g, user_id, target))

        if kind == NightKind.KILL:
            g.evil_votes[user_id] = target
            actor = g.players[user_id]
            relay = texts.EVIL_VOTE_RELAY.format(actor=texts.mention(user_id, actor.name),
                                                 target=texts.mention(target, target_name))
            for ally in g.evil_voters():
                if ally.user_id != user_id:
                    self._bg(self.m.send(ally.user_id, relay))
        else:
            g.actions[f"{user_id}:{slot}"] = Action(user_id, kind, target)
        self._resolve_slot(user_id, slot)
        return Reply(texts.NIGHT_CHOSEN.format(target=target_name))

    def _resolve_slot(self, user_id: int, slot: str) -> None:
        """Слот вирішено: прибираємо кнопки з інших підказок цього слоту."""
        mids = self._pending.pop((user_id, slot), [])
        for mid in mids:
            self._bg(self.m.clear_markup(user_id, mid))
        self._poke()

    async def _clear_pending(self, text: str) -> None:
        pending, self._pending = self._pending, {}
        for (uid, _), mids in pending.items():
            for mid in mids:
                await self.m.edit(uid, mid, text)

    async def _morning(self) -> None:
        g = self.game
        leader_before = g.evil_leader()
        res = resolve_night(g)
        hide = g.settings.get("hide_dead_roles", False)

        deaths = []
        for uid, cause in res.deaths:
            p = g.players[uid]
            deaths.append((uid, p.name, cause, None if hide else p.role_obj.title))
        await self.m.send(self.chat_id, texts.morning(g.day, deaths, len(res.saved)))

        name = lambda uid: texts.mention(uid, g.players[uid].name)  # noqa: E731
        private: list[tuple[int, str]] = []
        private += [(uid, texts.YOU_DIED) for uid, _ in res.deaths]
        private += [(uid, texts.YOU_SAVED[how]) for uid, how in res.saved]
        private += [(uid, texts.YOU_LURED) for uid in res.lured]
        private += [(uid, texts.GARLIC_WORKED) for uid in res.garlic]
        for actor, (target, village) in res.checks.items():
            private.append((actor, texts.CHECK_RESULT[village].format(target=name(target))))
        for actor, (a, b, same) in res.compares.items():
            private.append((actor, texts.COMPARE_RESULT[same].format(a=name(a), b=name(b))))
        for actor, (target, visitors) in res.watches.items():
            if visitors:
                private.append((actor, texts.WATCH_RESULT.format(
                    target=name(target), visitors=", ".join(name(v) for v in visitors))))
            else:
                private.append((actor, texts.WATCH_NOBODY.format(target=name(target))))
        for owner, visitors in res.candles.items():
            private.append((owner, texts.CANDLE_RESULT.format(visitors=", ".join(name(v) for v in visitors))))
        leader_after = g.evil_leader()
        if leader_after and leader_before and leader_after.user_id != leader_before.user_id:
            private.append((leader_after.user_id, texts.NEW_EVIL_LEADER))
        dead_now = {uid for uid, _ in res.deaths}
        for uid, text in private:
            if uid in dead_now and text != texts.YOU_DIED:
                continue
            await self.m.send(uid, text)

        if not await self._check_end():
            g.phase = Phase.DAY

    # ================= день =================

    async def _day(self) -> None:
        seconds = int(self.game.settings.get("day_time", 60))
        await self.m.send(self.chat_id, texts.DAY_START.format(time=texts.fmt_seconds(seconds)))
        await self._wait(seconds)
        self.game.phase = Phase.VOTE

    async def _vote(self) -> None:
        g = self.game
        g.votes.clear()
        g.honey_voters.clear()
        g.candidate = None
        self._pending.clear()
        seconds = int(g.settings.get("vote_time", 45))
        await self.m.send(self.chat_id, texts.VOTE_START.format(time=texts.fmt_seconds(seconds)),
                          views.to_bot_keyboard(self.bot_username))
        for p in g.alive():
            if is_bot_player(p.user_id):
                continue
            mid = await self.m.send(p.user_id, texts.VOTE_PROMPT, views.vote_keyboard(g, p.user_id))
            if mid:
                self._pending[(p.user_id, "vote")] = [mid]
        for p in self._bots():
            targets = [t.user_id for t in g.alive() if t.user_id != p.user_id]
            target = SKIP if random.random() < 0.15 else random.choice(targets)
            self._pending[(p.user_id, "vote")] = []
            self._bot_later(lambda uid=p.user_id, t=target: self.vote(uid, t))
        await self._wait(seconds, lambda: not self._pending or vote_decided(g))
        self._cancel_bot_moves()
        early = bool(self._pending) and vote_decided(g)
        await self._clear_pending(texts.VOTE_EARLY if early else texts.VOTE_EXPIRED)
        await self._flush()

        candidate, counts = tally(g)
        rows = []
        for target, count in counts.most_common():
            label = texts.VOTE_SKIP_LABEL if target == SKIP else texts.mention(target, g.players[target].name)
            rows.append((label, count))
        await self.m.send(self.chat_id, texts.vote_results(rows))
        if candidate is None:
            await self.m.send(self.chat_id, texts.VOTE_NOBODY)
            self._next_night()
            return
        g.candidate = candidate
        g.phase = Phase.CONFIRM

    def vote(self, user_id: int, target: int) -> Reply:
        g = self.game
        if g.phase != Phase.VOTE or (user_id, "vote") not in self._pending:
            return Reply(texts.NIGHT_NOT_NOW, alert=True)
        if not can_vote(g, user_id, target):
            return Reply(texts.NIGHT_BAD_TARGET, alert=True)
        self._pending.pop((user_id, "vote"), None)
        self._record_vote(user_id, target)
        if target == SKIP:
            return Reply(texts.VOTE_SKIP_CAST)
        return Reply(texts.VOTE_CAST.format(target=g.players[target].name))

    def _record_vote(self, user_id: int, target: int) -> None:
        g = self.game
        g.votes[user_id] = target
        self._poke()

        voter = texts.mention(user_id, g.players[user_id].name)
        if g.settings.get("secret_vote"):
            note = texts.VOTE_ANNOUNCE_SECRET.format(count=len(g.votes), total=len(g.alive()))
        elif target == SKIP:
            note = texts.VOTE_ANNOUNCE_SKIP.format(voter=voter)
        else:
            note = texts.VOTE_ANNOUNCE.format(voter=voter, target=texts.mention(target, g.players[target].name))
        self._bg(self.m.send(self.chat_id, note))

    def honey(self, user_id: int) -> Reply:
        g = self.game
        if g.phase != Phase.VOTE or (user_id, "vote") not in self._pending or not use_honey(g, user_id):
            return Reply(texts.HONEY_FAIL, alert=True)
        return Reply(texts.HONEY_USED + "\n\n" + texts.VOTE_PROMPT, markup=views.vote_keyboard(g, user_id))

    # ================= підтвердження страти =================

    def _confirm_text(self) -> str:
        g = self.game
        _, yes, no = confirm_result(g)
        return texts.CONFIRM_ASK.format(name=texts.mention(g.candidate, g.players[g.candidate].name), yes=yes, no=no)

    async def _confirm(self) -> None:
        g = self.game
        g.confirm.clear()
        self._confirm_mid = await self.m.send(self.chat_id, self._confirm_text(), views.confirm_keyboard(self.chat_id))
        self._confirm_open = True
        eligible = {p.user_id for p in g.alive() if p.user_id != g.candidate}
        for p in self._bots():
            if p.user_id != g.candidate:
                agree = random.random() < 0.6
                self._bot_later(lambda uid=p.user_id, a=agree: self.confirm_vote(uid, a))
        await self._wait(int(g.settings.get("confirm_time", 30)),
                         lambda: eligible <= set(g.confirm) or confirm_decided(g))
        self._confirm_open = False
        self._cancel_bot_moves()
        await self._flush()
        if self._confirm_mid:
            await self.m.edit(self.chat_id, self._confirm_mid, self._confirm_text())

        ok, yes, no = confirm_result(g)
        cand = g.players[g.candidate]
        cand_name = texts.mention(cand.user_id, cand.name)
        if not ok:
            await self.m.send(self.chat_id, texts.PARDON.format(name=cand_name, yes=yes, no=no))
        else:
            result = lynch(g, cand.user_id)
            if result.horseshoe:
                await self.m.send(self.chat_id, texts.HORSESHOE_SAVED.format(name=cand_name))
            else:
                hide = g.settings.get("hide_dead_roles", False)
                role = "" if hide else f"\n<i>Роль: {cand.role_obj.title}</i>"
                await self.m.send(self.chat_id, texts.LYNCHED.format(name=cand_name, role=role))
                if result.fool:
                    await self.m.send(self.chat_id, texts.FOOL_WON)
        g.candidate = None
        if not await self._check_end():
            self._next_night()

    def confirm_vote(self, user_id: int, yes: bool) -> Reply:
        g = self.game
        p = g.players.get(user_id)
        if not self._confirm_open:
            return Reply(texts.CONFIRM_CLOSED, alert=True)
        if g.phase != Phase.CONFIRM or not p or not p.alive or user_id == g.candidate:
            return Reply(texts.CONFIRM_NOT_ALLOWED, alert=True)
        g.confirm[user_id] = yes
        self._poke()
        self._live_edit(self._confirm_mid, lambda: (self._confirm_text(), views.confirm_keyboard(self.chat_id)))
        return Reply(texts.CONFIRM_THANKS, alert=False)

    def _next_night(self) -> None:
        self.game.day += 1
        self.game.phase = Phase.NIGHT

    # ================= нечиста рада =================

    def evil_chat_targets(self, user_id: int) -> list[int]:
        g = self.game
        p = g.players.get(user_id)
        if g.phase in (Phase.LOBBY, Phase.FINISHED) or not p or not p.alive or p.team != Team.EVIL:
            return []
        return [a.user_id for a in g.team_alive(Team.EVIL) if a.user_id != user_id]

    # ================= кінець гри =================

    async def _check_end(self) -> bool:
        winner = check_winner(self.game)
        if winner is None:
            return False
        await self._finish(winner)
        return True

    async def _finish(self, winner: str) -> None:
        g = self.game
        g.winner = winner
        win_ids = winners(g, winner)
        win_lines, lose_lines = [], []
        results = []
        for p in g.players.values():
            won = p.user_id in win_ids
            reward = economy.game_reward(won, p.vip)
            results.append((p.user_id, p.role, won, reward))
            name = texts.mention(p.user_id, p.name)
            line = f"{name if p.alive else f'<s>{name}</s>'} — {p.role_obj.title}"
            (win_lines if won else lose_lines).append(line)
        over = texts.game_over(winner, win_lines, lose_lines, g.day)
        if self.is_test:
            await self.m.send(self.chat_id, over + "\n\n" + texts.TEST_GAME_NOTE)
            g.phase = Phase.FINISHED
            return
        await self.m.send(self.chat_id, over)
        await games_db.record_result(self.pool, self.chat_id, str(winner), g.day, results)
        for uid, _, won, reward in results:
            await self.m.send(uid, texts.REWARD_PM.format(
                result=texts.RESULT_WIN if won else texts.RESULT_LOSE, amount=texts.shagy(reward)))
        await self._return_pockets()
        g.phase = Phase.FINISHED

    async def _return_pockets(self) -> None:
        for p in self.game.players.values():
            if p.pocket:
                items, p.pocket = p.pocket, []
                try:
                    await shop_db.return_items(self.pool, p.user_id, items)
                except Exception:
                    log.exception("Failed to return items to %s", p.user_id)
