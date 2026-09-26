"""Денне голосування і страта."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from bot.engine import items as it
from bot.engine.models import Game

SKIP = 0


def vote_weight(game: Game, uid: int) -> int:
    weight = 1
    if "vote2" in game.players[uid].role_obj.passives:
        weight += 1
    if uid in game.honey_voters:
        weight += 1
    return weight


def can_vote(game: Game, voter: int, target: int) -> bool:
    p = game.players.get(voter)
    if not p or not p.alive:
        return False
    if target == SKIP:
        return True
    t = game.players.get(target)
    return t is not None and t.alive and target != voter


def use_honey(game: Game, uid: int) -> bool:
    p = game.players.get(uid)
    if not p or not p.alive or uid in game.honey_voters or not p.use(it.HONEY):
        return False
    game.honey_voters.append(uid)
    return True


def tally(game: Game) -> tuple[int | None, Counter]:
    """Повертає (кандидат на страту або None, зважені голоси)."""
    counts: Counter = Counter()
    for voter, target in game.votes.items():
        if game.players[voter].alive:
            counts[target] += vote_weight(game, voter)
    ranked = [(t, c) for t, c in counts.most_common() if t != SKIP]
    if not ranked:
        return None, counts
    top_target, top = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == top:
        return None, counts  # нічия
    if counts.get(SKIP, 0) >= top:
        return None, counts
    return top_target, counts


def max_weight(game: Game, uid: int) -> int:
    """Найбільша вага, яку ще може мати голос гравця (з урахуванням нез'їденого меду)."""
    weight = vote_weight(game, uid)
    if uid not in game.honey_voters and game.players[uid].has(it.HONEY):
        weight += 1
    return weight


def vote_decided(game: Game) -> bool:
    """Чи вже ніщо не змінить підсумок денного голосування (лідер недосяжний для решти)."""
    remaining = sum(max_weight(game, p.user_id) for p in game.alive() if p.user_id not in game.votes)
    if remaining == 0:
        return True
    _, counts = tally(game)
    ranked = counts.most_common()
    if not ranked:
        return False
    best_other = ranked[1][1] if len(ranked) > 1 else 0
    return ranked[0][1] > best_other + remaining


def confirm_decided(game: Game) -> bool:
    """Чи вже ніщо не змінить вирок (страчувати чи ні)."""
    remaining = sum(
        vote_weight(game, p.user_id) for p in game.alive()
        if p.user_id != game.candidate and p.user_id not in game.confirm
    )
    _, yes, no = confirm_result(game)
    return yes > no + remaining or no >= yes + remaining


def confirm_result(game: Game) -> tuple[bool, int, int]:
    """(страчувати?, зважене «так», зважене «ні»). Кандидат сам не голосує."""
    yes = no = 0
    for voter, agree in game.confirm.items():
        if voter == game.candidate or not game.players[voter].alive:
            continue
        w = vote_weight(game, voter)
        if agree:
            yes += w
        else:
            no += w
    return yes > no, yes, no


@dataclass
class LynchResult:
    user_id: int
    died: bool
    horseshoe: bool = False
    fool: bool = False


def lynch(game: Game, uid: int) -> LynchResult:
    p = game.players[uid]
    if p.use(it.HORSESHOE):
        return LynchResult(uid, died=False, horseshoe=True)
    p.alive = False
    if p.role == "duren":
        game.fool_won = True
        return LynchResult(uid, died=True, fool=True)
    return LynchResult(uid, died=True)
