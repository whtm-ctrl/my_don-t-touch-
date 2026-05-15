"""
Database connection and session management.
Uses SQLAlchemy with asyncpg for async PostgreSQL operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator
import structlog

from config import settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database sessions.
    Yields a session and ensures proper cleanup.
    """
    session = async_session_maker()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error("Database session error", error=str(e))
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """
    Initialize database tables.
    Should be called on application startup.
    """
    try:
        async with engine.begin() as conn:
            # Import all models to ensure they are registered
            from scraper import models  # noqa: F401
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        raise


async def close_db() -> None:
    """
    Close database connections.
    Should be called on application shutdown.
    """
    await engine.dispose()
    logger.info("Database connections closed")
