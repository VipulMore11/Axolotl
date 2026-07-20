"""
Bitbucket OAuth Service.
Handles the OAuth 2.0 authorization code flow with Bitbucket Cloud:
  - Build authorization URL
  - Exchange code for tokens
  - Fetch authenticated user profile
"""

import os
from typing import Any, Dict

import httpx


class BitbucketOAuthService:
    """Encapsulates all Bitbucket Cloud OAuth 2.0 operations."""

    def __init__(self) -> None:
        pass

    @property
    def client_id(self) -> str:
        return os.getenv("BITBUCKET_CLIENT_ID", "")

    @property
    def client_secret(self) -> str:
        return os.getenv("BITBUCKET_CLIENT_SECRET", "")

    @property
    def redirect_uri(self) -> str:
        return os.getenv("BITBUCKET_REDIRECT_URI", "http://localhost:8000/auth/bitbucket/callback")

    # ── Step 1: Redirect user to Bitbucket ──────────────────────────

    def get_authorization_url(self) -> str:
        """
        Build the Bitbucket OAuth authorization URL.

        Returns:
            Full URL to redirect the user to for authorization.
        """
        params = (
            f"client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&response_type=code"
        )
        return f"https://bitbucket.org/site/oauth2/authorize?{params}"

    # ── Step 2: Exchange authorization code for tokens ───────────────

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchange an authorization code for an access token.

        Bitbucket uses HTTP Basic auth (client_id:client_secret) for the token endpoint.

        Args:
            code: The authorization code from Bitbucket callback.

        Returns:
            Dict with access_token, refresh_token, token_type, etc.

        Raises:
            httpx.HTTPStatusError: If the token exchange fails.
        """
        token_url = "https://bitbucket.org/site/oauth2/access_token"
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=payload,
                auth=(self.client_id, self.client_secret),
            )
            response.raise_for_status()
            return response.json()

    # ── Step 3: Fetch authenticated user profile ────────────────────

    async def get_bitbucket_user(self, access_token: str) -> Dict[str, Any]:
        """
        Fetch the authenticated Bitbucket user's profile.

        Args:
            access_token: Valid Bitbucket OAuth access token.

        Returns:
            Dict with uuid, username, display_name, links (avatar), etc.

        Raises:
            httpx.HTTPStatusError: If the API call fails.
        """
        user_url = "https://api.bitbucket.org/2.0/user"
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
        token_url = "https://bitbucket.org/site/oauth2/access_token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=payload,
                auth=(self.client_id, self.client_secret),
            )
            response.raise_for_status()
            return response.json()
