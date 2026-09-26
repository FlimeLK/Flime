"""Умови перемоги."""

from __future__ import annotations

from bot.engine.models import Game
from bot.engine.roles import Team

DRAW = "draw"


def check_winner(game: Game) -> str | None:
    """Повертає переможну сторону (Team.* або DRAW) або None, якщо гра триває.

    Іван-дурень перемагає окремо (game.fool_won) і не зупиняє гру.
    """
    alive = game.alive()
    if not alive:
        return DRAW
    evil = len(game.team_alive(Team.EVIL))
    wolf = len(game.team_alive(Team.WOLF))
    others = len(alive) - evil - wolf

    if wolf:
        if len(alive) <= 2:
            return Team.WOLF
        return None
    if evil == 0:
        return Team.VILLAGE
    if evil >= others:
        return Team.EVIL
    return None


def winners(game: Game, winner: str) -> set[int]:
    """Хто з гравців отримує перемогу."""
    result: set[int] = set()
    if winner in (Team.VILLAGE, Team.EVIL, Team.WOLF):
        result = {p.user_id for p in game.players.values() if p.team == winner}
    if game.fool_won:
        result |= {p.user_id for p in game.players.values() if p.role == "duren"}
    return result
