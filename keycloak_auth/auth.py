import logging
import os
from typing import Any, Dict, List, Optional

import httpx
import jwt
from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field

from .user_mapping import build_authenticated_user_payload, resolve_or_create_local_user_from_claims

load_dotenv(dotenv_path=".env")
logger = logging.getLogger(__name__)

KEYCLOAK_ISSUER = (os.getenv("KEYCLOAK_ISSUER") or "").rstrip("/")
KEYCLOAK_JWKS_URL = (os.getenv("KEYCLOAK_JWKS_URL") or "").strip()
KEYCLOAK_AUDIENCE = (os.getenv("KEYCLOAK_AUDIENCE") or "").strip()
KEYCLOAK_CLIENT_ID = (os.getenv("KEYCLOAK_CLIENT_ID") or "").strip()
KEYCLOAK_ALGORITHMS = [
    algo.strip()
    for algo in (os.getenv("KEYCLOAK_ALGORITHMS") or "RS256").split(",")
    if algo.strip()
]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/user/login/")


class AuthenticatedUser(BaseModel):
    id: str
    keycloak_sub: Optional[str] = None
    username: Optional[str] = None
    username_email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    organization: Optional[Any] = None
    incorporation: Optional[str] = Field(default=None)
    address: Optional[str] = Field(default=None)
    vat_no: Optional[str] = Field(default=None)
    position_title: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    roles: List[str] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=list)
    is_admin: Optional[bool] = False


_JWKS_CLIENT: Optional[jwt.PyJWKClient] = None
_token_cache: TTLCache = TTLCache(maxsize=500, ttl=60)
_http_client = httpx.AsyncClient(timeout=5.0)


def _build_keycloak_jwks_url() -> str:
    if KEYCLOAK_JWKS_URL:
        return KEYCLOAK_JWKS_URL
    if not KEYCLOAK_ISSUER:
        raise HTTPException(status_code=500, detail="KEYCLOAK_ISSUER environment variable not set")
    return f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs"


def get_jwks_client() -> jwt.PyJWKClient:
    global _JWKS_CLIENT
    if _JWKS_CLIENT is None:
        _JWKS_CLIENT = jwt.PyJWKClient(_build_keycloak_jwks_url())
    return _JWKS_CLIENT


def collect_keycloak_roles(claims: Dict[str, Any]) -> List[str]:
    #
    # Aggregate every role the token exposes into one normalized list.
    # Keycloak can place roles in two common areas:
    # 1. `realm_access.roles` for realm-wide roles
    # 2. `resource_access[client].roles` for client-specific roles
    # The rest of the application consumes a flat role list, so this helper
    # merges both sources, removes duplicates, and returns a stable order.


    roles = set()
    # Collect realm-level roles such as platform-wide admin or user roles.
    realm_access = claims.get("realm_access") or {}
    for role in realm_access.get("roles") or []:
        if role:
            roles.add(str(role))

    # Collect client-level roles from every resource entry present in the token.
    resource_access = claims.get("resource_access") or {}
    for client_access in resource_access.values():
        for role in (client_access or {}).get("roles") or []:
            if role:
                roles.add(str(role))

    # Return a sorted list so downstream comparisons and logs are deterministic.
    return sorted(roles)


def collect_keycloak_groups(claims: Dict[str, Any]) -> List[str]:
    groups = claims.get("groups") or []
    if isinstance(groups, list):
        return sorted(str(group) for group in groups if group)
    return []


def merge_keycloak_userinfo(claims: Dict[str, Any], userinfo: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(claims)
    attributes = dict((claims.get("attributes") or {}))

    for key, value in userinfo.items():
        if key == "attributes" and isinstance(value, dict):
            attributes.update(value)
        elif value is not None:
            merged[key] = value

    if attributes:
        merged["attributes"] = attributes
    return merged


async def enrich_keycloak_claims(token: str, claims: Dict[str, Any]) -> Dict[str, Any]:
    response = await _http_client.get(
        f"{KEYCLOAK_ISSUER}/protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code != 200:
        logger.warning(
            "Keycloak userinfo lookup failed with status %s: %s",
            response.status_code,
            response.text,
        )
        return claims

    userinfo = response.json()
    if isinstance(userinfo, dict):
        return merge_keycloak_userinfo(claims, userinfo)
    return claims


async def verify_access(request: Request, authorization: Optional[str] = Header(None)) -> None:


    unauthenticated_paths = {"/docs", "/openapi.json", "/user/login/", "/user/register"}
    if request.url.path in unauthenticated_paths:
        return
    if not authorization:
        return
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header format, expected: Bearer <token>", headers={"WWW-Authenticate": "Bearer"})

    token = authorization.split(" ", 1)[1]
    if token in _token_cache:
        return
    if not KEYCLOAK_ISSUER:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="KEYCLOAK_ISSUER is not configured on the server")

    response = await _http_client.get(
        f"{KEYCLOAK_ISSUER}/protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code != 200:
        logger.warning(
            "Keycloak userinfo validation fallback for token cache failed with status %s: %s",
            response.status_code,
            response.text,
        )
    _token_cache[token] = True


def decode_keycloak_token(token: str) -> Dict[str, Any]:

    # Build the standard 401 response used when the bearer token is missing,
    # malformed, expired, signed by the wrong key, or otherwise invalid.

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # The issuer identifies the Keycloak realm that is allowed to mint tokens
    # for this service. Without it we cannot safely verify the JWT.

    if not KEYCLOAK_ISSUER:
        raise HTTPException(status_code=500, detail="KEYCLOAK_ISSUER environment variable not set")
    try:
        # Resolve the signing key from Keycloak JWKS using the JWT header `kid`.
        # This lets the service verify tokens locally without calling Keycloak for every request.

        signing_key = get_jwks_client().get_signing_key_from_jwt(token)

        # Prepare JWT verification settings:
        # - `key` is the resolved public key
        # - `algorithms` restricts accepted signing algorithms
        # - `issuer` ensures the token comes from the configured realm
        # - `verify_aud` is enabled only when an audience/client is configured

        decode_kwargs = {
            "key": signing_key.key,
            "algorithms": KEYCLOAK_ALGORITHMS,
            "issuer": KEYCLOAK_ISSUER,
            "options": {"verify_aud": bool(KEYCLOAK_AUDIENCE or KEYCLOAK_CLIENT_ID)},
        }

        # When configured, require the token audience to match this API's expected Keycloak client identifier.
        expected_audience = KEYCLOAK_AUDIENCE or KEYCLOAK_CLIENT_ID
        if expected_audience:
            decode_kwargs["audience"] = expected_audience

        # Decode the JWT and return its claims as a Python dictionary.
        claims = jwt.decode(token, **decode_kwargs)
        claims["_keycloak_roles"] = collect_keycloak_roles(claims)
        claims["_keycloak_groups"] = collect_keycloak_groups(claims)
        return claims
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Keycloak token verification failed: %s", exc)
        raise credentials_exception


async def verify_keycloak_token_and_get_current_user(token: str = Depends(oauth2_scheme)) -> AuthenticatedUser:

    # Verify the incoming Keycloak JWT and decode it into token claims.
    claims = decode_keycloak_token(token)
    claims = await enrich_keycloak_claims(token, claims)

    # Resolve the matching local Mongo user, creating a placeholder record if needed.
    user = await resolve_or_create_local_user_from_claims(claims, logger)

    # Extract Keycloak roles from the decoded claims for authorization decisions.
    roles = claims.get("_keycloak_roles") or collect_keycloak_roles(claims)
    groups = claims.get("_keycloak_groups") or collect_keycloak_groups(claims)

    user_payload = build_authenticated_user_payload(user, claims)

    return AuthenticatedUser(
        **user_payload,
        roles=roles,
        groups=groups,
        is_admin=bool(user.get("is_admin") or ("admin" in roles)),
    )
