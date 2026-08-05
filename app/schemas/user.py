from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.models.user import UserRole, AuthProvider

class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    role: UserRole = UserRole.STUDENT
    exam_code: Optional[str] = None

class UserCreate(UserBase):
    password: Optional[str] = None

class StaffCreate(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    role: UserRole
    exam_code: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class RoleUpdate(BaseModel):
    role: UserRole
    exam_code: Optional[str] = None

class UserRead(UserBase):
    id: UUID
    auth_provider: AuthProvider
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
