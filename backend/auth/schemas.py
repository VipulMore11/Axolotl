"""
Pydantic schemas for authentication.
Defines User models and token response shapes.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserInDB(BaseModel):
    """Full user document as stored in MongoDB."""

    id: Optional[str] = Field(None, alias="_id")
    gitlab_user_id: int
    username: str
    name: str
    avatar_url: Optional[str] = None
    access_token: str
    refresh_token: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class UserResponse(BaseModel):
    """Safe public user response — no tokens exposed."""

    id: str
    gitlab_user_id: int
    username: str
    name: str
    avatar_url: Optional[str] = None


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
