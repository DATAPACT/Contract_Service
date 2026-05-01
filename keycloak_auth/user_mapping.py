import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

USER_MONGO_URI = (os.getenv("USER_MONGO_URI") or "").strip()
USER_MONGO_USER = os.getenv("USER_MONGO_USER")
USER_MONGO_PASSWORD = os.getenv("USER_MONGO_PASSWORD")
USER_MONGO_HOST = os.getenv("USER_MONGO_HOST")
USER_MONGO_PORT = os.getenv("USER_MONGO_PORT")
USER_MONGO_DB = os.getenv("USER_MONGO_DB", "dips_services")

MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT")


def _build_mongo_uri(user: Optional[str], password: Optional[str], host: Optional[str], port: Optional[str]) -> str:
    if port:
        return f"mongodb://{user}:{password}@{host}:{int(port)}"
    return f"mongodb+srv://{user}:{password}@{host}/?retryWrites=true&w=majority&appName=Cluster0"


def _build_user_mongo_uri() -> str:
    if USER_MONGO_URI:
        return USER_MONGO_URI
    if USER_MONGO_HOST and USER_MONGO_USER and USER_MONGO_PASSWORD:
        return _build_mongo_uri(USER_MONGO_USER, USER_MONGO_PASSWORD, USER_MONGO_HOST, USER_MONGO_PORT)
    return _build_mongo_uri(MONGO_USER, MONGO_PASSWORD, MONGO_HOST, MONGO_PORT)


users_client = AsyncIOMotorClient(_build_user_mongo_uri())
users_db = users_client[USER_MONGO_DB]
users_collection = users_db.users


def build_full_name(first_name: Optional[str], last_name: Optional[str]) -> Optional[str]:
    parts = [part.strip() for part in [first_name or "", last_name or ""] if part and part.strip()]
    return " ".join(parts) or None


def _claim_attribute_value(claims: Dict[str, Any], *keys: str) -> Optional[Any]:
    attributes = claims.get("attributes") or {}
    value = None
    for key in keys:
        value = claims.get(key)
        if value is None:
            value = attributes.get(key)
        if value is not None:
            break
    if isinstance(value, list):
        if len(value) == 1:
            return value[0]
        return value
    return value


def _clean_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalize_organization_claim(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or None
    cleaned = str(value).strip()
    return [cleaned] if cleaned else None


async def resolve_or_create_local_user_from_claims(claims: Dict[str, Any], log: Optional[logging.Logger] = None) -> Dict[str, Any]:

    # `sub` is the stable Keycloak subject identifier and the primary link between the external identity and the local Mongo user document.
    # keycloak_id

    keycloak_sub = claims.get("sub")
    if not keycloak_sub:
        raise HTTPException(status_code=401, detail="Keycloak token missing subject")

    username_email = claims.get("email") or claims.get("preferred_username")
    first_name = (claims.get("given_name") or "").strip() or None
    last_name = (claims.get("family_name") or "").strip() or None
    display_name = build_full_name(first_name, last_name)
    username = (claims.get("preferred_username") or "").strip() or None
    user_type = _clean_optional_string(_claim_attribute_value(claims, "user_type", "type"))
    organization = _normalize_organization_claim(_claim_attribute_value(claims, "organization", "Organization"))
    incorporation = _clean_optional_string(_claim_attribute_value(claims, "incorporation"))
    address = _clean_optional_string(_claim_attribute_value(claims, "address"))
    vat_no = _clean_optional_string(_claim_attribute_value(claims, "VAT_No"))
    position_title = _clean_optional_string(_claim_attribute_value(claims, "positionTitle", "PositionTitle"))
    phone = _clean_optional_string(_claim_attribute_value(claims, "phone"))
    roles = claims.get("_keycloak_roles") or []
    groups = claims.get("_keycloak_groups") or []

    now = datetime.utcnow()

    # First try the canonical lookup by Keycloak subject. This is the safest
    # mapping once a local user has already been linked to Keycloak

    user = await users_collection.find_one({"$or": [{"keycloak_sub": keycloak_sub},
                                                    {"keycloak_user_id": keycloak_sub}]})

    if not user and username_email:

        # When migrating existing users to Keycloak, first try to match the
        # existing user document by email and then bind it to the Keycloak `sub`.

        user = await users_collection.find_one({"username_email": username_email})
        if user:
            bind_fields = {
                "keycloak_sub": keycloak_sub,
                "updated_at": now,
                "last_login_at": now,
            }
            if first_name:
                bind_fields["first_name"] = first_name
            if last_name:
                bind_fields["last_name"] = last_name
            if display_name:
                bind_fields["name"] = display_name
            if username:
                bind_fields["username"] = username
            if user_type:
                bind_fields["type"] = user_type
            if organization:
                bind_fields["organization"] = organization
            if incorporation:
                bind_fields["incorporation"] = incorporation
            if address:
                bind_fields["address"] = address
            if vat_no:
                bind_fields["vat_no"] = vat_no
            if position_title:
                bind_fields["position_title"] = position_title
            if phone:
                bind_fields["phone"] = phone
            await users_collection.update_one(
                {"_id": user["_id"]},
                {"$set": bind_fields},
            )
            user = await users_collection.find_one({"_id": user["_id"]})

    if not user:
        # Provision a local placeholder business profile on first Keycloak login
        # so contract ownership and access control can continue using a local Mongo `_id`.

        placeholder_value = "miss value"
        username_email = username_email or f"{keycloak_sub}@missing.local"
        first_name = first_name or placeholder_value
        last_name = last_name or placeholder_value
        display_name = build_full_name(first_name, last_name) or placeholder_value
        placeholder_type = user_type or placeholder_value
        new_user = {
            "keycloak_sub": keycloak_sub,
            "first_name": first_name,
            "last_name": last_name,
            "name": display_name,
            "username": username,
            "type": placeholder_type,
            "username_email": username_email,
            "password": None,
            "organization": organization or [placeholder_value],
            "incorporation": incorporation or placeholder_value,
            "address": address or placeholder_value,
            "vat_no": vat_no or placeholder_value,
            "position_title": position_title or placeholder_value,
            "phone": phone or placeholder_value,
            "roles": roles,
            "groups": groups,
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        }
        (log or logger).warning(
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
        if username and user.get("username") != username:
            update_fields["username"] = username
        if user_type and user.get("type") != user_type:
            update_fields["type"] = user_type
        if organization and user.get("organization") != organization:
            update_fields["organization"] = organization
        if incorporation and user.get("incorporation") != incorporation:
            update_fields["incorporation"] = incorporation
        if address and user.get("address") != address:
            update_fields["address"] = address
        if vat_no and user.get("vat_no") != vat_no:
            update_fields["vat_no"] = vat_no
        if position_title and user.get("position_title") != position_title:
            update_fields["position_title"] = position_title
        if phone and user.get("phone") != phone:
            update_fields["phone"] = phone
        if roles:
            update_fields["roles"] = roles
        if groups:
            update_fields["groups"] = groups
        if not user.get("keycloak_sub"):
            update_fields["keycloak_sub"] = keycloak_sub
        if update_fields:
            await users_collection.update_one({"_id": user["_id"]}, {"$set": update_fields})
            user = await users_collection.find_one({"_id": user["_id"]})

    return user


def build_authenticated_user_payload(user: Dict[str, Any], claims: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "keycloak_sub": claims.get("sub"),
        "username": user.get("username") or claims.get("preferred_username"),
        "username_email": user.get("username_email") or claims.get("email"),
        "first_name": user.get("first_name") or claims.get("given_name"),
        "last_name": user.get("last_name") or claims.get("family_name"),
        "name": user.get("name") or claims.get("name"),
        "type": user.get("type") or claims.get("user_type") or claims.get("type"),
        "organization": user.get("organization"),
        "incorporation": user.get("incorporation"),
        "address": user.get("address"),
        "vat_no": user.get("vat_no"),
        "position_title": user.get("position_title"),
        "phone": user.get("phone"),
    }
