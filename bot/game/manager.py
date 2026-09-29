"""Реєстр активних ігор."""

from __future__ import annotations

import logging

import asyncpg

from bot.db import games as games_db
from bot.db.groups import GroupSettings
from bot.engine.models import Game, Phase
from bot.engine.roles import register_custom
from bot.game.messenger import Messenger
from bot.game.runner import GameRunner

log = logging.getLogger(__name__)


class GameManager:
    def __init__(self, messenger: Messenger, pool: asyncpg.Pool, bot_username: str):
        self.m = messenger
        self.pool = pool
        self.bot_username = bot_username
        self.runners: dict[int, GameRunner] = {}

    def get(self, chat_id: int) -> GameRunner | None:
        return self.runners.get(chat_id)

    def runner_of_user(self, user_id: int) -> GameRunner | None:
        for runner in self.runners.values():
            if user_id in runner.game.players and runner.game.phase != Phase.FINISHED:
                return runner
        return None

    def _make(self, game: Game, title: str = "") -> GameRunner:
        runner = GameRunner(game, self.m, self.pool, self.bot_username, self._finished, chat_title=title)
        self.runners[game.chat_id] = runner
        return runner

    def create(self, chat_id: int, settings: GroupSettings, starter_id: int, title: str,
               custom_roles: list[dict] | None = None) -> GameRunner:
        game = Game(chat_id=chat_id, settings={**settings.to_dict(), "custom_roles": custom_roles or []},
                    starter_id=starter_id)
        runner = self._make(game, title)
        runner.start()
        return runner

    def _finished(self, chat_id: int) -> None:
        self.runners.pop(chat_id, None)

    async def restore(self) -> int:
        """Відновлює ігри, що йшли до перезапуску бота."""
        count = 0
        for state in await games_db.load_snapshots(self.pool):
            try:
                game = Game.from_dict(state)
            except Exception:
                log.exception("Broken game snapshot, dropping: %s", state.get("chat_id"))
                await games_db.delete_snapshot(self.pool, state.get("chat_id"))
                continue
            register_custom(game.settings.get("custom_roles", []))
            if game.phase == Phase.FINISHED:
                await games_db.delete_snapshot(self.pool, game.chat_id)
                continue
            self._make(game).start(resumed=True)
            count += 1
        return count

    async def shutdown(self) -> None:
        for runner in list(self.runners.values()):
            await runner.shutdown()
