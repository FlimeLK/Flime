"""Снапшоти активних ігор і результати завершених."""

from __future__ import annotations

import json

import asyncpg


async def save_snapshot(pool: asyncpg.Pool, chat_id: int, state: dict) -> None:
    await pool.execute(
        "INSERT INTO games (chat_id, state, updated_at) VALUES ($1, $2::jsonb, now()) "
        "ON CONFLICT (chat_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
        chat_id, json.dumps(state, ensure_ascii=False),
    )


async def delete_snapshot(pool: asyncpg.Pool, chat_id: int) -> None:
    await pool.execute("DELETE FROM games WHERE chat_id = $1", chat_id)


async def load_snapshots(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch("SELECT state FROM games")
    return [json.loads(r["state"]) for r in rows]


async def record_result(
    pool: asyncpg.Pool,
    chat_id: int,
    winner: str,
    days: int,
    players: list[tuple[int, str, bool, int]],
) -> None:
    """players: (user_id, role, won, reward_shagy)."""
    async with pool.acquire() as conn, conn.transaction():
        game_id = await conn.fetchval(
            "INSERT INTO game_results (chat_id, winner, players, days) VALUES ($1, $2, $3, $4) RETURNING id",
            chat_id, winner, len(players), days,
        )
        await conn.executemany(
            "INSERT INTO game_players (game_id, user_id, role, won) VALUES ($1, $2, $3, $4)",
            [(game_id, uid, role, won) for uid, role, won, _ in players],
        )
        await conn.executemany(
            "UPDATE users SET games = games + 1, wins = wins + $2::int, shagy = shagy + $3 WHERE id = $1",
            [(uid, 1 if won else 0, reward) for uid, _, won, reward in players],
        )


async def top_for_chat(pool: asyncpg.Pool, chat_id: int, limit: int = 10) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT u.id, u.name, count(*) FILTER (WHERE gp.won) AS wins, count(*) AS games "
        "FROM game_players gp JOIN game_results gr ON gr.id = gp.game_id JOIN users u ON u.id = gp.user_id "
        "WHERE gr.chat_id = $1 GROUP BY u.id, u.name ORDER BY wins DESC, games DESC LIMIT $2",
        chat_id, limit,
    )
