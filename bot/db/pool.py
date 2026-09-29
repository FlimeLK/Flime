"""Пул підключень asyncpg і застосування міграцій."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

SCHEMA = "hutir"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

log = logging.getLogger(__name__)


LEGACY_SCHEMA = "hutir_legacy"
REF_SCHEMA = "hutir_ref"


async def _init_connection(conn: asyncpg.Connection) -> None:
    # Дублюємо search_path командою: деякі пулери (pgbouncer тощо) ігнорують параметри старту.
    await conn.execute(f"SET search_path TO {SCHEMA}")


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
        init=_init_connection,
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
            await _repair_foreign_tables(conn)
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


async def _columns(conn: asyncpg.Connection, schema: str) -> dict[str, set[str]]:
    rows = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = $1", schema)
    result: dict[str, set[str]] = {}
    for r in rows:
        result.setdefault(r["table_name"], set()).add(r["column_name"])
    return result


async def _repair_foreign_tables(conn: asyncpg.Connection) -> None:
    """Якщо в схемі лежить таблиця з нашою назвою, але чужою структурою (наприклад, від старого бота),
    переносимо її в схему hutir_legacy (дані зберігаються) і створюємо правильну."""
    sql = [path.read_text(encoding="utf-8") for path in sorted(MIGRATIONS_DIR.glob("*.sql"))]
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {REF_SCHEMA} CASCADE; CREATE SCHEMA {REF_SCHEMA}")
        await conn.execute(f"SET LOCAL search_path TO {REF_SCHEMA}")
        # Для кожної таблиці - колонки з моменту її створення: пізніші міграції (ADD COLUMN)
        # ще можуть бути не застосовані, і це не робить таблицю «чужою».
        expected: dict[str, set[str]] = {}
        for text in sql:
            await conn.execute(text)
            for table, cols in (await _columns(conn, REF_SCHEMA)).items():
                expected.setdefault(table, cols)
    finally:
        await tr.rollback()

    actual = await _columns(conn, SCHEMA)
    broken = [t for t, cols in expected.items() if t in actual and not cols <= actual[t]]
    if not broken:
        return
    async with conn.transaction():
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {LEGACY_SCHEMA}")
        for table in broken:
            await conn.execute(f"DROP TABLE IF EXISTS {LEGACY_SCHEMA}.{table} CASCADE")
            await conn.execute(f"ALTER TABLE {SCHEMA}.{table} SET SCHEMA {LEGACY_SCHEMA}")
            log.warning("Table %s had a foreign structure, moved to %s.%s", table, LEGACY_SCHEMA, table)
        # Відтворюємо перенесені таблиці (міграції ідемпотентні).
        await conn.execute(f"SET LOCAL search_path TO {SCHEMA}")
        for text in sql:
            await conn.execute(text)
