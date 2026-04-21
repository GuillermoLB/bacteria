from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from bacteria.settings import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.postgres.url,
            pool_size=10,
            max_overflow=5,
        )
    return _engine


@asynccontextmanager
async def get_connection() -> AsyncIterator[AsyncConnection]:
    async with get_engine().connect() as conn:
        yield conn
