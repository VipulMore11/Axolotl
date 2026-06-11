"""
JWT authentication utilities for Axolotl.
Provides token creation, verification, and a FastAPI dependency
for extracting the current authenticated user.
"""

import os
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from auth.schemas import UserResponse
from db.mongo_service import get_mongo_service

# ── Configuration ────────────────────────────────────────────────────

JWT_SECRET: str = os.getenv("JWT_SECRET", "axolotl-dev-secret-change-me")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRY_HOURS: int = 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/gitlab/login", auto_error=False)


# ── Token creation ───────────────────────────────────────────────────

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT.

    Args:
        data: Payload dict (must include "user_id").
        expires_delta: Custom expiry duration. Defaults to 24 hours.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(hours=JWT_EXPIRY_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ── Token verification ──────────────────────────────────────────────

def verify_access_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT.

    Args:
        token: The JWT string.

    Returns:
        Decoded payload dict.

    Raises:
        HTTPException(401): If the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependency ───────────────────────────────────────────────

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
) -> UserResponse:
    """
    FastAPI dependency that extracts and validates the current user from a JWT.

    Usage:
        @router.get("/protected")
        async def protected(user: UserResponse = Depends(get_current_user)):
            ...

    Raises:
        HTTPException(401): If no token or invalid token.
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_access_token(token)
    user_id: Optional[str] = payload.get("user_id")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    mongo = get_mongo_service()
    user_doc = await mongo.get_user_by_id(user_id)

    if user_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return UserResponse(
        id=str(user_doc["_id"]),
        gitlab_user_id=user_doc["gitlab_user_id"],
        username=user_doc["username"],
        name=user_doc["name"],
        avatar_url=user_doc.get("avatar_url"),
    )
