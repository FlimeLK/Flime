import asyncio

import pytest

from tests.conftest import DSN


async def _fresh_conn():
    asyncpg = pytest.importorskip("asyncpg")
    try:
        conn = await asyncpg.connect(DSN, timeout=3)
    except Exception:
        pytest.skip("test database is not available")
    await conn.execute("DROP SCHEMA IF EXISTS hutir CASCADE")
    await conn.execute("DROP SCHEMA IF EXISTS hutir_legacy CASCADE")
    return conn


async def test_apply_twice(pool):
    from bot.db.pool import apply_migrations

    await apply_migrations(pool)
    await apply_migrations(pool)
    assert await pool.fetchval("SELECT count(*) FROM custom_roles") == 0


async def test_old_public_table_does_not_interfere():
    conn = await _fresh_conn()
    await conn.execute("DROP TABLE IF EXISTS public.custom_roles")
    await conn.execute("CREATE TABLE public.custom_roles (id INT, legacy TEXT)")
    try:
        from bot.db.pool import create_pool

        p = await create_pool(DSN)
        try:
            schema = await p.fetchval(
                "SELECT table_schema FROM information_schema.columns"
                " WHERE table_name = 'custom_roles' AND column_name = 'ability'"
            )
            assert schema == "hutir"
        finally:
            await p.close()
    finally:
        await conn.execute("DROP TABLE IF EXISTS public.custom_roles")
        await conn.close()


async def test_parallel_start():
    conn = await _fresh_conn()
    await conn.close()
    from bot.db.pool import create_pool

    pools = await asyncio.gather(create_pool(DSN), create_pool(DSN))
    for p in pools:
        await p.close()


async def test_foreign_table_in_schema_is_replaced():
    conn = await _fresh_conn()
    await conn.execute("CREATE SCHEMA hutir")
    await conn.execute(
        "CREATE TABLE hutir.custom_roles (role_id SERIAL PRIMARY KEY, group_id BIGINT, role_name TEXT)")
    await conn.execute("INSERT INTO hutir.custom_roles (group_id, role_name) VALUES (1, 'old')")
    await conn.close()
    from bot.db import roles as roles_db
    from bot.db.pool import create_pool

    p = await create_pool(DSN)
    try:
        assert await roles_db.list_for_chat(p, 1) == []
        rid = await roles_db.create(p, 1, 1, name="X", emoji="🙂", emoji_id=None, description="",
                                    team="village", ability="check", min_players=4)
        assert (await roles_db.get(p, rid))["name"] == "X"
        assert await p.fetchval("SELECT role_name FROM hutir_legacy.custom_roles") == "old"
        await p.close()
        p = await create_pool(DSN)  # повторний старт нічого не ламає
        assert len(await roles_db.list_for_chat(p, 1)) == 1
    finally:
        await p.close()


async def test_new_columns_do_not_mark_table_foreign():
    """Стара версія нашої таблиці (без колонок з пізніших міграцій) лишається на місці з даними."""
    conn = await _fresh_conn()
    await conn.execute("CREATE SCHEMA hutir")
    await conn.execute("SET search_path TO hutir")
    from bot.db.pool import MIGRATIONS_DIR

    await conn.execute(
        "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    for path in sorted(MIGRATIONS_DIR.glob("*.sql"))[:3]:
        await conn.execute(path.read_text(encoding="utf-8"))
        await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", path.stem)
    await conn.execute("INSERT INTO group_settings (chat_id, title, night_time) VALUES (-5, 'Сім''я', 120)")
    await conn.close()
    from bot.db import groups
    from bot.db.pool import create_pool

    p = await create_pool(DSN)
    try:
        s = await groups.get(p, -5)
        assert s.night_time == 120 and s.title == "Сім'я" and s.mafia_ratio == "normal"
        assert await p.fetchval("SELECT to_regclass('hutir_legacy.group_settings')") is None
    finally:
        await p.close()
