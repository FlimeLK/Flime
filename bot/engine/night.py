"""Резолвер ночі.

Порядок:
  1. Мавка заманює - дія цілі скасовується (якщо в неї немає часнику).
  2. Визначається жертва нечисті (слово ватажка, інакше більшість голосів).
  3. Фіксуються візити (для сторожа й свічки).
  4. Знахарка лікує.
  5. Перевірки характерника й кобзаря.
  6. Вбивства: лікування → оберіг → везіння кума → смерть.
  7. Інформація: сторож, свічка.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from bot.engine import items as it
from bot.engine.models import Action, Game
from bot.engine.roles import NightKind, Team

KILL_KINDS = (NightKind.KILL, NightKind.WOLF_KILL, NightKind.SABER, NightKind.PITCHFORK, NightKind.CUSTOM_KILL)


@dataclass
class NightResult:
    # (жертва, причина) - причина: evil | wolf | saber | pitchfork
    deaths: list[tuple[int, str]] = field(default_factory=list)
    # (врятований, чим) - heal | obereg | kum
    saved: list[tuple[int, str]] = field(default_factory=list)
    # кого заманила мавка (їхня дія скасована)
    lured: list[int] = field(default_factory=list)
    # гравці, яких захистив часник
    garlic: list[int] = field(default_factory=list)
    # характерник: хто → (кого, чи з Громади)
    checks: dict[int, tuple[int, bool]] = field(default_factory=dict)
    # кобзар: хто → (a, b, одна сторона?)
    compares: dict[int, tuple[int, int, bool]] = field(default_factory=dict)
    # сторож: хто → (за ким стежив, хто приходив)
    watches: dict[int, tuple[int, list[int]]] = field(default_factory=dict)
    # свічка: власник → хто приходив
    candles: dict[int, list[int]] = field(default_factory=dict)
    evil_target: int | None = None


def side(game: Game, uid: int) -> Team:
    """Сторона для кобзаря: дурень вважається Громадою."""
    team = game.players[uid].team
    return Team.VILLAGE if team == Team.FOOL else team


def evil_target(game: Game, lured: set[int]) -> tuple[int | None, int | None]:
    """Повертає (ціль, хто «приходив» від нечисті)."""
    votes = {v: t for v, t in game.evil_votes.items() if v not in lured and game.players[v].alive}
    if not votes:
        return None, None
    leader = game.evil_leader()
    if leader and leader.user_id in votes:
        return votes[leader.user_id], leader.user_id
    counts = Counter(votes.values()).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return None, None  # нечисть не домовилась
    target = counts[0][0]
    visitor = next(v for v, t in votes.items() if t == target)
    return target, visitor


def resolve_night(game: Game) -> NightResult:
    res = NightResult()
    alive = set(game.alive_ids())
    actions = [a for a in game.actions.values() if a.actor in alive and a.target in alive]

    # 1. Мавка
    lured: set[int] = set()
    for a in actions:
        if a.kind != NightKind.LURE:
            continue
        target = game.players[a.target]
        if target.use(it.GARLIC):
            res.garlic.append(a.target)
        else:
            lured.add(a.target)
    res.lured = sorted(lured)
    actions = [a for a in actions if a.actor not in lured or a.kind == NightKind.LURE]

    # 2. Жертва нечисті
    target, visitor = evil_target(game, lured)
    res.evil_target = target
    if target is not None and target in alive:
        actions.append(Action(visitor, NightKind.KILL, target))

    # 3. Візити
    visits: dict[int, list[int]] = {}
    for a in actions:
        for t in (a.target, a.target2):
            if t is not None and t != a.actor:
                visits.setdefault(t, [])
                if a.actor not in visits[t]:
                    visits[t].append(a.actor)

    # 4. Лікування
    healed: set[int] = set()
    for a in actions:
        if a.kind == NightKind.HEAL:
            healed.add(a.target)
            healer = game.players[a.actor]
            healer.flags["last_heal"] = a.target
            if a.target == a.actor:
                healer.flags["self_healed"] = True

    # 5. Перевірки
    for a in actions:
        if a.kind == NightKind.CHECK:
            target_p = game.players[a.target]
            looks_village = target_p.team in (Team.VILLAGE, Team.FOOL) or target_p.use(it.MASK)
            res.checks[a.actor] = (a.target, looks_village)
        elif a.kind == NightKind.COMPARE and a.target2 is not None and a.target2 in alive:
            res.compares[a.actor] = (a.target, a.target2, side(game, a.target) == side(game, a.target2))

    # 6. Вбивства
    attacks: dict[int, list[str]] = {}
    for a in actions:
        if a.kind not in KILL_KINDS:
            continue
        cause = {
            NightKind.KILL: "evil", NightKind.WOLF_KILL: "wolf",
            NightKind.SABER: "saber", NightKind.PITCHFORK: "pitchfork", NightKind.CUSTOM_KILL: "custom",
        }[a.kind]
        if a.kind == NightKind.SABER:
            game.players[a.actor].flags["saber_used"] = True
        if a.kind == NightKind.PITCHFORK:
            game.players[a.actor].use(it.PITCHFORK)
        attacks.setdefault(a.target, []).append(cause)

    for victim_id, causes in attacks.items():
        victim = game.players[victim_id]
        if victim_id in healed:
            res.saved.append((victim_id, "heal"))
        elif victim.use(it.OBEREG):
            res.saved.append((victim_id, "obereg"))
        elif victim.role == "kum" and not victim.flags.get("kum_saved"):
            victim.flags["kum_saved"] = True
            res.saved.append((victim_id, "kum"))
        else:
            res.deaths.append((victim_id, causes[0]))

    for victim_id, _ in res.deaths:
        game.players[victim_id].alive = False

    # 7. Інформація
    for a in actions:
        if a.kind == NightKind.WATCH:
            res.watches[a.actor] = (a.target, [v for v in visits.get(a.target, []) if v != a.actor])
    for uid in alive:
        p = game.players[uid]
        if p.alive and p.has(it.CANDLE) and visits.get(uid):
            p.use(it.CANDLE)
            res.candles[uid] = list(visits[uid])

    # Знахарка, яка цієї ночі не лікувала, може знову лікувати будь-кого.
    for p in game.by_role("znaharka"):
        if not any(a.actor == p.user_id and a.kind == NightKind.HEAL for a in actions):
            p.flags.pop("last_heal", None)

    return res


def can_target(game: Game, actor_id: int, kind: NightKind, target_id: int) -> bool:
    """Чи дозволена ціль для нічної дії."""
    actor = game.players.get(actor_id)
    target = game.players.get(target_id)
    if not actor or not target or not actor.alive or not target.alive:
        return False
    if kind not in game.night_kinds(actor):
        return False
    if kind == NightKind.HEAL:
        if target_id == actor_id and actor.flags.get("self_healed"):
            return False
        if actor.flags.get("last_heal") == target_id:
            return False
        return True
    if kind in (NightKind.KILL,):
        return target.team != Team.EVIL
    if kind == NightKind.LURE:
        # Мавка (і будь-яка нечисть) не блокує своїх; блокувальник з інших сторін — будь-кого.
        return target_id != actor_id and (actor.team != Team.EVIL or target.team != Team.EVIL)
    # Решта дій - будь-хто, крім себе.
    return target_id != actor_id
