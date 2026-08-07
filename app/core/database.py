import asyncio
from typing import Any
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool
from app.core.config import settings

DATABASE_URL = settings.RESOLVED_DATABASE_URL

class AsyncSessionWrapper:
    """
    Wraps a synchronous SQLAlchemy Session to provide an AsyncSession interface
    for non-async drivers like libsql_experimental (Turso).
    """
    def __init__(self, sync_session):
        self._session = sync_session

    async def execute(self, statement, *args, **kwargs):
        return await asyncio.to_thread(self._session.execute, statement, *args, **kwargs)

    async def commit(self):
        return await asyncio.to_thread(self._session.commit)

    async def refresh(self, instance, *args, **kwargs):
        return await asyncio.to_thread(self._session.refresh, instance, *args, **kwargs)

    async def close(self):
        return await asyncio.to_thread(self._session.close)

    def add(self, instance):
        self._session.add(instance)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await asyncio.to_thread(self._session.rollback)
        await self.close()

from sqlalchemy.dialects import registry

try:
    registry.register("sqlite.https", "sqlalchemy_libsql", "SQLiteDialect_libsql")
except Exception:
    pass

if "libsql" in DATABASE_URL or "https" in DATABASE_URL:
    connect_args: dict[str, Any] = {}
    if settings.TURSO_AUTH_TOKEN:
        connect_args["auth_token"] = settings.TURSO_AUTH_TOKEN.strip().strip("'").strip('"')
    
    sync_engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        poolclass=NullPool,
        pool_pre_ping=True
    )
    engine = sync_engine
    SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
    
    def get_async_session():
        return AsyncSessionWrapper(SyncSessionLocal())

else:
    async_engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
    )
    engine = async_engine
    AsyncSessionLocal = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    def get_async_session():
        return AsyncSessionLocal()

Base = declarative_base()


async def init_db():
    """Auto-create database tables if they do not exist."""
    import app.models.user  # noqa: F401
    import app.models.session  # noqa: F401

    if "libsql" in DATABASE_URL or "https" in DATABASE_URL:
        # Retry mechanism for Turso cold starts (502 Bad Gateway)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await asyncio.to_thread(Base.metadata.create_all, bind=sync_engine)
                break
            except Exception as e:
                if "502" in str(e) and attempt < max_retries - 1:
                    print(f"Database wake-up retry {attempt + 1}/{max_retries}. Waiting 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    raise e
    else:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

