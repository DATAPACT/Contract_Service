import os
from typing import Optional

import httpx
from cachetools import TTLCache
from fastapi import Header, HTTPException, status

KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER")

# Cache validated tokens for 60 s to avoid a Keycloak round-trip on every request.
_token_cache: TTLCache = TTLCache(maxsize=500, ttl=60)

# Persistent client — reused across requests for connection pooling.
_http_client = httpx.AsyncClient(timeout=5.0)


async def verify_access(
    authorization: Optional[str] = Header(None),
) -> None:
    """
    Two-mode auth dependency:
      - Standalone (no Authorization header): passes through, no auth required.
      - Iframe / SSO mode (Authorization: Bearer <token> present): validated against Keycloak /userinfo.
    """
    if not authorization:
        return

    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format, expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1]

    if token in _token_cache:
        return

    if not KEYCLOAK_ISSUER:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KEYCLOAK_ISSUER is not configured on the server",
        )

    response = await _http_client.get(
        f"{KEYCLOAK_ISSUER}/protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired Keycloak token",
        )

    _token_cache[token] = True