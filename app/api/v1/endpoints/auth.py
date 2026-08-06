from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime, timedelta, timezone
from typing import Optional
import httpx
import base64
import json
from uuid import UUID

from app.core.security import generate_session_token
from app.core.config import settings
from app.api.deps import get_db, get_current_user, oauth2_scheme, invalidate_session_cache
from app.models.user import User, AuthProvider, UserRole
from app.models.session import Session
from app.schemas.auth import TokenResponse
from app.schemas.user import UserRead, StaffCreate, RoleUpdate

router = APIRouter()

@router.get("/google/login")
async def google_login(
    request: Request,
    role: UserRole = Query(...),
    exam_code: Optional[str] = Query(None)
):
    """
    Redirects the user to Google's OAuth 2.0 consent screen.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
        
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    redirect_uri = f"{base_url}{settings.API_V1_STR}/auth/google/callback"
    
    # Encode role and exam_code into the state parameter
    state_data = {"role": role.value if role else UserRole.STUDENT.value, "exam_code": exam_code}
    state_b64 = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={settings.GOOGLE_CLIENT_ID}&"
        f"response_type=code&"
        f"redirect_uri={redirect_uri}&"
        f"scope=openid%20email%20profile&"
        f"access_type=offline&"
        f"state={state_b64}"
    )
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Handles the Google OAuth callback, exchanges code for token, and issues our stateful session token.
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
        
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    redirect_uri = f"{base_url}{settings.API_V1_STR}/auth/google/callback"
    
    # 1. Exchange code for access token and id_token
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to authenticate with Google")
            
        token_data = response.json()
        access_token = token_data.get("access_token")
        
        # 2. Get user info
        user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        user_info_response = await client.get(user_info_url, headers=headers)
        
        if user_info_response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to retrieve user info from Google")
            
        user_info = user_info_response.json()
        
    email = user_info.get("email")
    name = user_info.get("name")
    
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email not provided by Google")
        
    # Decode the state parameter to get role and exam_code
    assigned_role = UserRole.STUDENT
    assigned_exam_code = None
    if state:
        try:
            # Re-pad the base64 string if necessary
            padding = '=' * (4 - len(state) % 4)
            state_json = base64.urlsafe_b64decode((state + padding).encode()).decode()
            state_data = json.loads(state_json)
            if "role" in state_data and state_data["role"] in [r.value for r in UserRole]:
                assigned_role = UserRole(state_data["role"])
            assigned_exam_code = state_data.get("exam_code")
        except Exception as e:
            print(f"Failed to parse state parameter: {e}")
            pass # ignore invalid state payload, fall back to defaults
            
    # 3. Find or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    
    if not user:
        if assigned_role in [UserRole.TEACHER, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You are not authorized to register as a Teacher or Admin. Please contact support."
            )
            
        # Create new user
        user = User(
            email=email,
            name=name,
            auth_provider=AuthProvider.GOOGLE,
            role=assigned_role,
            exam_code=assigned_exam_code
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        # Check if an existing student is trying to log in as a teacher/admin
        if assigned_role == UserRole.TEACHER and user.role == UserRole.STUDENT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You do not have permission to log in as a Teacher."
            )
        if assigned_role == UserRole.ADMIN and user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You do not have permission to log in as an Admin."
            )
            
    if user.auth_provider != AuthProvider.GOOGLE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered with another provider")
        
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")


    # 4. Create stateful session
    session_token = generate_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    new_session = Session(
        user_id=user.id,
        session_token=session_token,
        expires_at=expires_at
    )
    db.add(new_session)
    await db.commit()
    
    # Redirect Teachers to 3000, Students and Admins to 9000
    frontend_url = "http://localhost:3000" if assigned_role == UserRole.TEACHER else "http://localhost:9000"
    
    return RedirectResponse(url=f"{frontend_url}/?token={session_token}")


@router.post("/register-staff", response_model=UserRead)
async def register_staff(
    staff_data: StaffCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Register a new Teacher or Admin.
    Only accessible by existing Admins.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can register staff members."
        )
        
    if staff_data.role not in [UserRole.ADMIN, UserRole.TEACHER]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be ADMIN or TEACHER."
        )

    # Check if user already exists
    result = await db.execute(select(User).where(User.email == staff_data.email))
    existing_user = result.scalars().first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists."
        )
        
    # Create pre-provisioned user
    new_user = User(
        email=staff_data.email,
        name=staff_data.name,
        auth_provider=AuthProvider.GOOGLE,
        role=staff_data.role,
        exam_code=staff_data.exam_code
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    return new_user


@router.put("/users/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: UUID,
    role_data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update an existing user's role.
    Only accessible by existing Admins.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can update roles."
        )
        
    if role_data.role not in [UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role."
        )

    # Check if user exists
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalars().first()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found."
        )
        
    # Update the user
    target_user.role = role_data.role  # type: ignore
    if role_data.exam_code is not None:
        target_user.exam_code = role_data.exam_code  # type: ignore
    elif role_data.role == UserRole.STUDENT or role_data.role == UserRole.ADMIN:
        # Optional: clear exam_code if not applicable
        # target_user.exam_code = None
        pass
        
    await db.commit()
    await db.refresh(target_user)
    
    return target_user


@router.get("/me", response_model=UserRead)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """
    Get current user profile.
    """
    return current_user


@router.post("/logout")
async def logout(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    """
    Logs out the current user by invalidating their session token.
    """
    invalidate_session_cache(token)
    await db.execute(delete(Session).where(Session.session_token == token))
    await db.commit()
    return {"message": "Successfully logged out"}

