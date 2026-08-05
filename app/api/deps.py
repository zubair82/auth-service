from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator, Any, Dict, Tuple
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import time

from app.core.database import get_async_session
from app.models.user import User
from app.models.session import Session
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"/api/v1/auth/google/login")

# In-memory TTL cache for session lookups: token -> (session, user, cached_time)
_SESSION_CACHE: Dict[str, Tuple[Session, User, float]] = {}
_CACHE_TTL_SECONDS = 30.0

def invalidate_session_cache(token: str):
    """Invalidate cached session when a user logs out."""
    _SESSION_CACHE.pop(token, None)

async def get_db() -> AsyncGenerator[Any, None]:
    async with get_async_session() as session:
        yield session

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    now = datetime.now(timezone.utc)
    current_time = time.time()

    # 1. Fast Path: Check in-memory TTL cache
    cached = _SESSION_CACHE.get(token)
    if cached:
        cached_session, cached_user, cached_at = cached
        if (current_time - cached_at) < _CACHE_TTL_SECONDS:
            expires_at = cached_session.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > now and cached_user.is_active:
                return cached_user
            else:
                _SESSION_CACHE.pop(token, None)

    # 2. Database Path: Single joined query fetching Session and User together
    result = await db.execute(
        select(Session, User)
        .join(User, Session.user_id == User.id)
        .where(Session.session_token == token)
    )
    row = result.first()
    
    if not row:
        _SESSION_CACHE.pop(token, None)
        raise credentials_exception
        
    session, user = row
        
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
        
    if expires_at < now:
        _SESSION_CACHE.pop(token, None)
        raise credentials_exception

    if user is None or not user.is_active:
        _SESSION_CACHE.pop(token, None)
        raise HTTPException(status_code=400, detail="Inactive user")

    # 3. Throttled Session Renewal: Only update DB if less than half expiration window remains
    half_ttl = (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60) / 2
    if (expires_at - now).total_seconds() < half_ttl:
        new_expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        session.expires_at = new_expires  # type: ignore
        db.add(session)
        await db.commit()

    # 4. Populate cache for subsequent requests
    _SESSION_CACHE[token] = (session, user, current_time)
        
    return user

