"""
GitLab OAuth Service.
Handles the OAuth 2.0 authorization code flow with GitLab:
  - Build authorization URL
  - Exchange code for tokens
  - Fetch authenticated user profile
"""

import os
from typing import Any, Dict

import httpx


class GitLabOAuthService:
    """Encapsulates all GitLab OAuth 2.0 operations."""

    def __init__(self) -> None:
        pass

    @property
    def client_id(self) -> str:
        return os.getenv("GITLAB_CLIENT_ID", "")

    @property
    def client_secret(self) -> str:
        return os.getenv("GITLAB_CLIENT_SECRET", "")

    @property
    def redirect_uri(self) -> str:
        return os.getenv("GITLAB_REDIRECT_URI", "http://localhost:8000/auth/gitlab/callback")

    @property
    def gitlab_base_url(self) -> str:
        return os.getenv("GITLAB_BASE_URL", "https://gitlab.com")

    # ── Step 1: Redirect user to GitLab ─────────────────────────────

    def get_authorization_url(self) -> str:
        """
        Build the GitLab OAuth authorization URL.

        Returns:
            Full URL to redirect the user to for authorization.
        """
        params = (
            f"client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&response_type=code"
            f"&scope=api"
        )
        return f"{self.gitlab_base_url}/oauth/authorize?{params}"

    # ── Step 2: Exchange authorization code for tokens ───────────────

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchange an authorization code for an access token.

        Args:
            code: The authorization code from GitLab callback.

        Returns:
            Dict with access_token, refresh_token, token_type, etc.

        Raises:
            httpx.HTTPStatusError: If the token exchange fails.
        """
        token_url = f"{self.gitlab_base_url}/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=payload)
            response.raise_for_status()
            return response.json()

    # ── Step 3: Fetch authenticated user profile ────────────────────

    async def get_gitlab_user(self, access_token: str) -> Dict[str, Any]:
        """
        Fetch the authenticated GitLab user's profile.

        Args:
            access_token: Valid GitLab OAuth access token.

        Returns:
            Dict with id, username, name, avatar_url, etc.

        Raises:
            httpx.HTTPStatusError: If the API call fails.
        """
        user_url = f"{self.gitlab_base_url}/api/v4/user"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(user_url, headers=headers)
            response.raise_for_status()
            return response.json()

    # ── Optional: Refresh an expired token ──────────────────────────

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an expired OAuth access token.

        Args:
            refresh_token: The refresh token from the original exchange.

        Returns:
            Dict with new access_token, refresh_token, etc.
        """
        token_url = f"{self.gitlab_base_url}/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "redirect_uri": self.redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=payload)
            response.raise_for_status()
            return response.json()
