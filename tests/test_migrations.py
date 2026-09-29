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
