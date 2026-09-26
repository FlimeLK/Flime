"""Пул підключень asyncpg і застосування міграцій."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

SCHEMA = "hutir"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

log = logging.getLogger(__name__)


async def create_pool(dsn: str) -> asyncpg.Pool:
    # Створюємо схему до відкриття пулу, щоб search_path одразу був валідний.
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    finally:
        await conn.close()
    pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=10,
        server_settings={"search_path": SCHEMA},
    )
    await apply_migrations(pool)
    return pool


async def apply_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.stem in applied:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", path.stem)
            log.info("Applied migration %s", path.stem)
