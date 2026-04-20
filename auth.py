import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import jwt
from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

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

MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT")
MONGO_DB = os.getenv("MONGO_DB", "datapack")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/user/login/")


def _build_mongo_uri(user: Optional[str], password: Optional[str], host: Optional[str], port: Optional[str]) -> str:
    if port:
        return f"mongodb://{user}:{password}@{host}:{int(port)}"
    return f"mongodb+srv://{user}:{password}@{host}/?retryWrites=true&w=majority&appName=Cluster0"


if MONGO_PORT:
    MONGO_PORT = int(MONGO_PORT)
    MONGO_URI = _build_mongo_uri(MONGO_USER, MONGO_PASSWORD, MONGO_HOST, str(MONGO_PORT))
else:
    MONGO_URI = _build_mongo_uri(MONGO_USER, MONGO_PASSWORD, MONGO_HOST, None)


users_client = AsyncIOMotorClient(MONGO_URI)
users_db = users_client[MONGO_DB]
users_collection = users_db.users


def _build_keycloak_jwks_url() -> str:
    if KEYCLOAK_JWKS_URL:
        return KEYCLOAK_JWKS_URL
    if not KEYCLOAK_ISSUER:
        raise HTTPException(status_code=500, detail="KEYCLOAK_ISSUER environment variable not set")
    return f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs"


_jwks_client: Optional[jwt.PyJWKClient] = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(_build_keycloak_jwks_url())
    return _jwks_client


class AuthenticatedUser(BaseModel):
    id: str
    keycloak_sub: Optional[str] = None
    username_email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    organization: Optional[Any] = None
    roles: List[str] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=list)
    is_admin: Optional[bool] = False

# Cache validated tokens for 60 s to avoid a Keycloak round-trip on every request.
_token_cache: TTLCache = TTLCache(maxsize=500, ttl=60)

# Persistent client — reused across requests for connection pooling.
_http_client = httpx.AsyncClient(timeout=5.0)


async def verify_access(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> None:
    """
    Two-mode auth dependency:
      - Standalone (no Authorization header): passes through, no auth required.
      - Iframe / SSO mode (Authorization: Bearer <token> present): validated against Keycloak /userinfo.
    """
    unauthenticated_paths = {
        "/docs",
        "/openapi.json",
        "/user/login/",
        "/user/register",
    }
    if request.url.path in unauthenticated_paths:
        return

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


def _collect_keycloak_roles(claims: Dict[str, Any]) -> List[str]:
    # Aggregate every role the token exposes into one normalized list.
    # Keycloak can place roles in two common areas:
    # 1. `realm_access.roles` for realm-wide roles
    # 2. `resource_access[client].roles` for client-specific roles
    # The rest of the application consumes a flat role list, so this helper
    # merges both sources, removes duplicates, and returns a stable order.
    roles = set()
    realm_access = claims.get("realm_access") or {}
    # Collect realm-level roles such as platform-wide admin or user roles.
    for role in realm_access.get("roles") or []:
        if role:
            roles.add(str(role))

    resource_access = claims.get("resource_access") or {}
    # Collect client-level roles from every resource entry present in the token.
    for client_access in resource_access.values():
        for role in (client_access or {}).get("roles") or []:
            if role:
                roles.add(str(role))

    # Return a sorted list so downstream comparisons and logs are deterministic.
    return sorted(roles)


def _collect_keycloak_groups(claims: Dict[str, Any]) -> List[str]:
    # Normalize the Keycloak `groups` claim into a predictable list of strings.
    # Some tokens may omit the claim entirely, so default to an empty list.
    groups = claims.get("groups") or []
    # Only accept the claim when it is already a list, then coerce each entry
    # to string, drop empty values, and sort for deterministic downstream use.
    if isinstance(groups, list):
        return sorted(str(group) for group in groups if group)
    # If the claim shape is unexpected, fail closed to "no groups" rather than
    # trusting malformed token content.
    return []


def _decode_keycloak_token(token: str) -> Dict[str, Any]:
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
        # This lets the service verify tokens locally without calling Keycloak
        # for every request.
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
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
        # When configured, require the token audience to match this API's
        # expected Keycloak client identifier.
        expected_audience = KEYCLOAK_AUDIENCE or KEYCLOAK_CLIENT_ID
        if expected_audience:
            decode_kwargs["audience"] = expected_audience
        # Decode the JWT and return its claims as a Python dictionary.
        return jwt.decode(token, **decode_kwargs)
    except HTTPException:
        # Preserve intentional HTTP errors unchanged.
        raise
    except Exception as exc:
        # Collapse all JWT/key parsing failures into one generic 401 so callers
        # do not receive internal verification details.
        logger.error("Keycloak token verification failed: %s", exc)
        raise credentials_exception


async def _get_or_create_local_user_from_claims(claims: Dict[str, Any]) -> Dict[str, Any]:
    # `sub` is the stable Keycloak subject identifier and the primary link
    # between the external identity and the local Mongo user document.
    keycloak_sub = claims.get("sub")
    if not keycloak_sub:
        raise HTTPException(status_code=401, detail="Keycloak token missing subject")

    # Extract the user profile fields we care about from the verified token.
    # These fields are used to look up an existing local user record and to
    # refresh local profile data on successful authentication.
    username_email = claims.get("email") or claims.get("preferred_username")
    first_name = (claims.get("given_name") or "").strip() or None
    last_name = (claims.get("family_name") or "").strip() or None
    display_name = " ".join(part for part in [first_name, last_name] if part) or claims.get("name") or claims.get("preferred_username") or username_email
    roles = _collect_keycloak_roles(claims)
    groups = _collect_keycloak_groups(claims)
    now = datetime.utcnow()

    # First try the canonical lookup by Keycloak subject. This is the safest
    # mapping once a local user has already been linked to Keycloak.
    user = await users_collection.find_one({"$or": [{"keycloak_sub": keycloak_sub}, {"keycloak_user_id": keycloak_sub}]})

    if not user and username_email:
        # When migrating existing users to Keycloak, first try to match the
        # existing user document by email and then bind it to the Keycloak `sub`.
        user = await users_collection.find_one({"username_email": username_email})
        if user:
            # Persist the Keycloak linkage and refresh basic profile fields so
            # future logins can use the stable `sub`-based lookup directly.
            await users_collection.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "keycloak_sub": keycloak_sub,
                        "first_name": first_name,
                        "last_name": last_name,
                        "name": display_name,
                        "updated_at": now,
                        "last_login_at": now,
                    }
                },
            )
            user = await users_collection.find_one({"_id": user["_id"]})

    if not user:
        # Provision a local placeholder business profile on first Keycloak login
        # so contract ownership and access control can continue using a local
        # Mongo `_id`.
        placeholder_value = "miss value"
        username_email = username_email or f"{keycloak_sub}@missing.local"
        first_name = first_name or placeholder_value
        last_name = last_name or placeholder_value
        display_name = " ".join(part for part in [first_name, last_name] if part) or placeholder_value
        placeholder_type = claims.get("type") or placeholder_value
        new_user = {
            "keycloak_sub": keycloak_sub,
            "first_name": first_name,
            "last_name": last_name,
            "name": display_name,
            "type": placeholder_type,
            "username_email": username_email,
            "password": None,
            "organization": [placeholder_value],
            "incorporation": placeholder_value,
            "address": placeholder_value,
            "vat_no": placeholder_value,
            "position_title": placeholder_value,
            "phone": placeholder_value,
            "roles": roles,
            "groups": groups,
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        }
        logger.warning(
            "Keycloak user %s (%s) is not registered in MongoDB. Creating placeholder local user with miss value defaults so contract processing can continue.",
            keycloak_sub,
            username_email,
        )
        insert_result = await users_collection.insert_one(new_user)
        user = await users_collection.find_one({"_id": insert_result.inserted_id})
    else:
        # Keep the local profile synchronized with the latest trusted Keycloak
        # claims while preserving app-specific fields already stored in Mongo.
        update_fields = {
            "updated_at": now,
            "last_login_at": now,
        }
        if username_email and user.get("username_email") != username_email:
            update_fields["username_email"] = username_email
        if first_name and user.get("first_name") != first_name:
            update_fields["first_name"] = first_name
        if last_name and user.get("last_name") != last_name:
            update_fields["last_name"] = last_name
        if display_name and user.get("name") != display_name:
            update_fields["name"] = display_name
        if roles:
            update_fields["roles"] = roles
        if groups:
            update_fields["groups"] = groups
        if not user.get("keycloak_sub"):
            update_fields["keycloak_sub"] = keycloak_sub
        if update_fields:
            await users_collection.update_one({"_id": user["_id"]}, {"$set": update_fields})
            user = await users_collection.find_one({"_id": user["_id"]})

    # Return the local Mongo user document that the rest of the API will treat
    # as the authenticated application user.
    return user


async def verify_keycloak_token_and_get_current_user(token: str = Depends(oauth2_scheme)) -> AuthenticatedUser:
    # Verify the incoming Keycloak JWT and decode it into token claims.
    claims = _decode_keycloak_token(token)
    # Resolve the matching local Mongo user, creating a placeholder record if needed.
    user = await _get_or_create_local_user_from_claims(claims)
    # Extract Keycloak roles from the decoded claims for authorization decisions.
    roles = _collect_keycloak_roles(claims)

    return AuthenticatedUser(
        id=str(user["_id"]),
        keycloak_sub=claims.get("sub"),
        username_email=user.get("username_email") or claims.get("email"),
        first_name=user.get("first_name") or claims.get("given_name"),
        last_name=user.get("last_name") or claims.get("family_name"),
        name=user.get("name") or claims.get("name"),
        type=user.get("type") or claims.get("type"),
        organization=user.get("organization"),
        roles=roles,
        groups=_collect_keycloak_groups(claims),
        is_admin=bool(user.get("is_admin") or ("admin" in roles)),
    )
