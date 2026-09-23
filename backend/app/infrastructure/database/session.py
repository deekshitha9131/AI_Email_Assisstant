from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession | None, None]:

    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        yield None
        return

    async with session_factory() as session:
        yield session
