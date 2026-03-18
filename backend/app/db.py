from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# Connection pool tuning — balances concurrency with connection overhead.
# pool_size=20      : base pool kept warm
# max_overflow=10   : up to 30 total connections under peak load
# pool_timeout=30   : wait up to 30s for a connection before raising
# pool_recycle=3600 : recycle connections every hour to avoid stale TCP issues
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
