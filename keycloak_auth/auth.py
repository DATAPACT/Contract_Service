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

from .user_mapping import resolve_or_create_local_user_from_claims

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
    roles = set()
    realm_access = claims.get("realm_access") or {}
    for role in realm_access.get("roles") or []:
        if role:
            roles.add(str(role))
    resource_access = claims.get("resource_access") or {}
    for client_access in resource_access.values():
        for role in (client_access or {}).get("roles") or []:
            if role:
                roles.add(str(role))
    return sorted(roles)


def collect_keycloak_groups(claims: Dict[str, Any]) -> List[str]:
    groups = claims.get("groups") or []
    if isinstance(groups, list):
        return sorted(str(group) for group in groups if group)
    return []


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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired Keycloak token")
    _token_cache[token] = True


def decode_keycloak_token(token: str) -> Dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not KEYCLOAK_ISSUER:
        raise HTTPException(status_code=500, detail="KEYCLOAK_ISSUER environment variable not set")
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        decode_kwargs = {
            "key": signing_key.key,
            "algorithms": KEYCLOAK_ALGORITHMS,
            "issuer": KEYCLOAK_ISSUER,
            "options": {"verify_aud": bool(KEYCLOAK_AUDIENCE or KEYCLOAK_CLIENT_ID)},
        }
        expected_audience = KEYCLOAK_AUDIENCE or KEYCLOAK_CLIENT_ID
        if expected_audience:
            decode_kwargs["audience"] = expected_audience
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
    claims = decode_keycloak_token(token)
    user = await resolve_or_create_local_user_from_claims(claims, logger)
    roles = claims.get("_keycloak_roles") or collect_keycloak_roles(claims)
    groups = claims.get("_keycloak_groups") or collect_keycloak_groups(claims)
    return AuthenticatedUser(
        id=str(user["_id"]),
        keycloak_sub=claims.get("sub"),
        username_email=user.get("username_email") or claims.get("email"),
        first_name=user.get("first_name") or claims.get("given_name"),
        last_name=user.get("last_name") or claims.get("family_name"),
        name=user.get("name") or claims.get("name"),
        type=user.get("type") or claims.get("type"),
        organization=user.get("organization"),
        incorporation=user.get("incorporation"),
        address=user.get("address"),
        vat_no=user.get("vat_no"),
        position_title=user.get("position_title"),
        phone=user.get("phone"),
        roles=roles,
        groups=groups,
        is_admin=bool(user.get("is_admin") or ("admin" in roles)),
    )
