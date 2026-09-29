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
        try:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        except asyncpg.UniqueViolationError:
            pass  # схему щойно створив інший екземпляр
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


# Будь-яке стале число: ключ блокування, щоб два екземпляри бота не мігрували одночасно.
MIGRATIONS_LOCK = 0x68757469


async def apply_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", MIGRATIONS_LOCK)
        try:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA}.schema_migrations ("
                " version TEXT PRIMARY KEY,"
                " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            applied = {
                r["version"] for r in await conn.fetch(f"SELECT version FROM {SCHEMA}.schema_migrations")
            }
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in applied:
                    continue
                async with conn.transaction():
                    # Таблиці завжди створюються в нашій схемі, навіть якщо в БД інший search_path.
                    await conn.execute(f"SET LOCAL search_path TO {SCHEMA}")
                    await conn.execute(path.read_text(encoding="utf-8"))
                    await conn.execute(
                        f"INSERT INTO {SCHEMA}.schema_migrations (version) VALUES ($1)"
                        " ON CONFLICT DO NOTHING",
                        path.stem,
                    )
                log.info("Applied migration %s", path.stem)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", MIGRATIONS_LOCK)
