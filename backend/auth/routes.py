"""
Authentication routes for Axolotl.
Implements the GitLab and Bitbucket OAuth 2.0 login flows and JWT session management.

Endpoints:
    GET  /auth/gitlab/login       — Redirect to GitLab OAuth
    GET  /auth/gitlab/callback    — Handle GitLab OAuth callback
    GET  /auth/bitbucket/login    — Redirect to Bitbucket OAuth
    GET  /auth/bitbucket/callback — Handle Bitbucket OAuth callback
    POST /auth/logout             — Logout (client-side token removal)
    GET  /auth/me                 — Get current authenticated user
"""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from auth.schemas import UserResponse, TokenResponse
from auth.service import GitLabOAuthService
from auth.bitbucket_service import BitbucketOAuthService
from core.auth import create_access_token, get_current_user
from db.mongo_service import get_mongo_service

router = APIRouter(prefix="/auth", tags=["authentication"])

# Service singletons
_gitlab_oauth_service = GitLabOAuthService()
_bitbucket_oauth_service = BitbucketOAuthService()


# ══════════════════════════════════════════════════════════════════════
# GitLab OAuth
# ══════════════════════════════════════════════════════════════════════

# ── GET /auth/gitlab/login ───────────────────────────────────────────

@router.get("/gitlab/login", summary="Redirect to GitLab OAuth")
async def gitlab_login():
    """
    Initiate the GitLab OAuth flow.
    Redirects the user to GitLab's authorization page.
    """
    authorization_url = _gitlab_oauth_service.get_authorization_url()
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
        token_data = await _gitlab_oauth_service.exchange_code_for_token(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")

        print(f"[AUTH] GitLab token exchange successful")

    except Exception as e:
        print(f"[AUTH ERROR] GitLab token exchange failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {str(e)}",
        )

    try:
        # Step 2: Fetch GitLab user profile
        gitlab_user = await _gitlab_oauth_service.get_gitlab_user(access_token)

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
        "provider": "gitlab",
        "gitlab_user_id": gitlab_user["id"],
        "provider_user_id": str(gitlab_user["id"]),
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


# ══════════════════════════════════════════════════════════════════════
# Bitbucket OAuth
# ══════════════════════════════════════════════════════════════════════

# ── GET /auth/bitbucket/login ────────────────────────────────────────

@router.get("/bitbucket/login", summary="Redirect to Bitbucket OAuth")
async def bitbucket_login():
    """
    Initiate the Bitbucket OAuth flow.
    Redirects the user to Bitbucket's authorization page.
    """
    authorization_url = _bitbucket_oauth_service.get_authorization_url()
    return RedirectResponse(url=authorization_url, status_code=302)


# ── GET /auth/bitbucket/callback ────────────────────────────────────

@router.get("/bitbucket/callback", summary="Bitbucket OAuth callback")
async def bitbucket_callback(code: str):
    """
    Handle the Bitbucket OAuth callback.

    Flow:
        1. Exchange authorization code for access token
        2. Fetch Bitbucket user profile
        3. Upsert user in MongoDB
        4. Issue JWT
        5. Redirect to frontend with token

    Args:
        code: Authorization code from Bitbucket.
    """
    try:
        # Step 1: Exchange code for tokens
        token_data = await _bitbucket_oauth_service.exchange_code_for_token(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")

        print(f"[AUTH] Bitbucket token exchange successful")

    except Exception as e:
        print(f"[AUTH ERROR] Bitbucket token exchange failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {str(e)}",
        )

    try:
        # Step 2: Fetch Bitbucket user profile
        bb_user = await _bitbucket_oauth_service.get_bitbucket_user(access_token)

        print(f"[AUTH] Bitbucket user fetched: {bb_user.get('username')}")

    except Exception as e:
        print(f"[AUTH ERROR] Failed to fetch Bitbucket user: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch Bitbucket user profile: {str(e)}",
        )

    # Step 3: Upsert user in MongoDB
    # Bitbucket user profile fields differ from GitLab:
    #   - uuid instead of id (integer)
    #   - display_name instead of name
    #   - links.avatar.href instead of avatar_url
    mongo = get_mongo_service()
    bb_uuid = bb_user.get("uuid", "").strip("{}")
    avatar_url = bb_user.get("links", {}).get("avatar", {}).get("href")

    user_data = {
        "provider": "bitbucket",
        "provider_user_id": bb_uuid,
        "username": bb_user.get("username", bb_user.get("nickname", "")),
        "name": bb_user.get("display_name", bb_user.get("username", "")),
        "avatar_url": avatar_url,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

    user_doc = await mongo.upsert_user(user_data)
    user_id = str(user_doc["_id"])

    print(f"[AUTH] Bitbucket user upserted: {user_id} ({user_data['username']})")

    # Step 4: Issue JWT
    jwt_token = create_access_token({"user_id": user_id})

    # Step 5: Redirect to frontend with token
    frontend_url = os.getenv("FRONTEND_URL")
    redirect_url = f"{frontend_url}/auth/callback?token={jwt_token}"

    return RedirectResponse(url=redirect_url, status_code=302)


# ══════════════════════════════════════════════════════════════════════
# Common
# ══════════════════════════════════════════════════════════════════════

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
