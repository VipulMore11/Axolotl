"""
Authentication routes for Axolotl.
Implements the GitLab OAuth 2.0 login flow and JWT session management.

Endpoints:
    GET  /auth/gitlab/login    — Redirect to GitLab OAuth
    GET  /auth/gitlab/callback — Handle OAuth callback
    POST /auth/logout          — Logout (client-side token removal)
    GET  /auth/me              — Get current authenticated user
"""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from auth.schemas import UserResponse, TokenResponse
from auth.service import GitLabOAuthService
from core.auth import create_access_token, get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/auth", tags=["authentication"])

# Service singleton
_oauth_service = GitLabOAuthService()


# ── GET /auth/gitlab/login ───────────────────────────────────────────

@router.get("/gitlab/login", summary="Redirect to GitLab OAuth")
async def gitlab_login():
    """
    Initiate the GitLab OAuth flow.
    Redirects the user to GitLab's authorization page.
    """
    authorization_url = _oauth_service.get_authorization_url()
    return RedirectResponse(url=authorization_url, status_code=302)


# ── GET /auth/gitlab/callback ───────────────────────────────────────

@router.get("/gitlab/callback", summary="GitLab OAuth callback")
async def gitlab_callback(code: str):
    """
    Handle the GitLab OAuth callback.

    Flow:
        1. Exchange authorization code for access token
        2. Fetch GitLab user profile
        3. Upsert user in MongoDB
        4. Issue JWT
        5. Redirect to frontend with token

    Args:
        code: Authorization code from GitLab.
    """
    try:
        # Step 1: Exchange code for tokens
        token_data = await _oauth_service.exchange_code_for_token(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")

        print(f"[AUTH] Token exchange successful")

    except Exception as e:
        print(f"[AUTH ERROR] Token exchange failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {str(e)}",
        )

    try:
        # Step 2: Fetch GitLab user profile
        gitlab_user = await _oauth_service.get_gitlab_user(access_token)

        print(f"[AUTH] GitLab user fetched: {gitlab_user.get('username')}")

    except Exception as e:
        print(f"[AUTH ERROR] Failed to fetch GitLab user: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch GitLab user profile: {str(e)}",
        )

    # Step 3: Upsert user in MongoDB
    mongo = get_mongo_service()
    user_data = {
        "gitlab_user_id": gitlab_user["id"],
        "username": gitlab_user["username"],
        "name": gitlab_user.get("name", gitlab_user["username"]),
        "avatar_url": gitlab_user.get("avatar_url"),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

    user_doc = await mongo.upsert_user(user_data)
    user_id = str(user_doc["_id"])

    print(f"[AUTH] User upserted: {user_id} ({gitlab_user['username']})")

    # Step 4: Issue JWT
    jwt_token = create_access_token({"user_id": user_id})

    # Step 5: Redirect to frontend with token
    frontend_url = os.getenv("FRONTEND_URL")
    redirect_url = f"{frontend_url}/auth/callback?token={jwt_token}"

    return RedirectResponse(url=redirect_url, status_code=302)


# ── POST /auth/logout ───────────────────────────────────────────────

@router.post("/logout", summary="Logout")
async def logout():
    """
    Logout endpoint.
    JWT is stateless so the client simply discards the token.
    This endpoint exists for API completeness.
    """
    return {"message": "Logged out successfully. Discard the token on the client."}


# ── GET /auth/me ─────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse, summary="Get current user")
async def get_me(user: UserResponse = Depends(get_current_user)):
    """
    Return the currently authenticated user's profile.

    Requires a valid JWT in the Authorization header.
    """
    return user
