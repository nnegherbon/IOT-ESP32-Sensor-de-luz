import os
import sys
from pathlib import Path

import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alerts import AlertEngine  # noqa: E402
from app.db import create_pool, migrate  # noqa: E402
from app.hub import Hub  # noqa: E402
from app.ingest import TelemetryService  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://luz:luz@localhost:5432/luz_test")


class RecordingHub(Hub):
    def __init__(self):
        super().__init__()
        self.sent: list[tuple[str, object]] = []

    async def broadcast(self, event_type, data):
        self.sent.append((event_type, data))

    def types(self):
        return [t for t, _ in self.sent]


async def reset_schema(dsn: str = TEST_DSN):
    pool = await create_pool(dsn)
    async with pool.acquire() as c:
        await c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await migrate(pool)
    return pool


@pytest_asyncio.fixture
async def pool():
    pool = await reset_schema()
    yield pool
    await pool.close()


async def build_service(pool, is_demo=False):
    hub = RecordingHub()
    alerts = AlertEngine(pool, hub, is_demo)
    await alerts.load()
    svc = TelemetryService(pool, hub, alerts, is_demo=is_demo)
    await svc.restore()
    return svc


@pytest_asyncio.fixture
async def service(pool):
    return await build_service(pool)
