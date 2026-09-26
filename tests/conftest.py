import os

import pytest

DSN = os.getenv("HUTIR_TEST_DSN", "postgresql://postgres:postgres@localhost:5432/hutir_test")


@pytest.fixture
async def pool():
    asyncpg = pytest.importorskip("asyncpg")
    try:
        conn = await asyncpg.connect(DSN, timeout=3)
    except Exception:
        pytest.skip("test database is not available")
    await conn.execute("DROP SCHEMA IF EXISTS hutir CASCADE")
    await conn.close()
    from bot.db.pool import create_pool

    p = await create_pool(DSN)
    yield p
    await p.close()
