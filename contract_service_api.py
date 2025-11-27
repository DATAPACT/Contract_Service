import logging
import os
import re
import traceback
import unicodedata
from datetime import datetime, date
from difflib import SequenceMatcher
from enum import Enum
from html import escape
from typing import Any, Dict, List, Literal, Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Body, HTTPException, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, AliasChoices
from pydantic import field_validator
from pymongo import ASCENDING, TEXT

from ca_generation import get_consent_contract_text, get_ca_contract_json
from dsa_generation import get_dsa_contract_text, get_dsa_contract_json
from utils import (text_to_pdf_bytes, TEXT_FIELDS, regex_or_query, create_odrl_decription, _to_bytes, summarize_text,
                   odrl_formate_convert, contract_to_turtle)

# Configure root logger once (e.g. at program entrypoint)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)
app = FastAPI(
    title="Contract Service API",
    description="UPCAST Contract Service API",
    openapi_url="/openapi.json",
    docs_url="/docs",
    version="1.0",
)

origins = [
    "*",
    "http://127.0.0.1:8866",
    "http://localhost:8866",
    "http://0.0.0.0:8866",
    # "http://dips.soton.ac.uk:8866",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MongoObject(BaseModel):
    id: Optional[object] = Field(None, alias="_id")

    @field_validator("id")
    def process_id(cls, value, values):
        if isinstance(value, ObjectId):
            return str(value)
        return value


class ClientOptionalInfo(BaseModel):
    # client_pid: Optional[str] = Field(None, alias="negotiation_id" or "consent_id")
    client_pid: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices('client_pid', 'request_id',
                                      'negotiation_id', 'consent_id'),
        serialization_alias='client_pid',  # keep output name as client_pid
    )

    policy_id: Optional[str] = Field(None)
    type: Optional[str] = Field(None)
    updated_at: Optional[datetime] = Field(None)


class UpcastContractObject(MongoObject):
    client_optional_info: Optional[ClientOptionalInfo] = None
    # Must be set; restricted to allowed values and defaults to "dsa"
    contract_type: Literal["dsa", "pda"] = Field( default="dsa", description="Type of contract.")
    cactus_format: Optional[bool] = Field(default=None, description="If truthy, run cactus ODRL conversion.")

    validity_period: Optional[int] = None
    notice_period: Optional[int] = None
    contacts: Optional[Dict[str, Any]] = Field(default_factory=dict)
    resource_description: Optional[Dict[str, Any]] = Field(default_factory=dict)
    definitions: Optional[Dict[str, Any]] = Field(default_factory=dict)

    # Your custom clauses extracted from odrl_policy_summary
    custom_clauses: Optional[Dict[str, Any]] = Field(default_factory=dict)
    dpw: Optional[Dict[str, Any]] = Field(default_factory=dict)
    odrl: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class UpcastSignatureObject(MongoObject):
    user_id: Optional[str] = None
    user_role: Optional[str] = None
    provider_signature: Optional[str] = None
    consumer_signature: Optional[str] = None
    provider_signature_date: Optional[datetime] = Field(default_factory=datetime.utcnow)
    consumer_signature_date: Optional[datetime] = Field(default_factory=datetime.utcnow)


def pydantic_to_dict(obj, clean_id=False):
    if isinstance(obj, list):
        return [pydantic_to_dict(item, clean_id) for item in obj]
    if isinstance(obj, dict):
        return {k: pydantic_to_dict(v, clean_id) for k, v in obj.items()}
    if isinstance(obj, BaseModel):
        return pydantic_to_dict(obj.dict(), clean_id)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, ObjectId) and clean_id:
        return str(obj)
    return obj


def normalize_bool(val) -> Optional[bool]:
    """Robustly parse boolean-like values."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int,)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in {"1", "true", "yes", "y"}:
            return True
        if s in {"0", "false", "no", "n"}:
            return False
    # Fallback: truthy/falsy by Python rules
    return bool(val)


# Load environment variables from .env file
# MONGO Connection Info

load_dotenv()
MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT")
if MONGO_PORT:  # Assumption: A local or remote installation of MongoDB is provided.
    MONGO_PORT = int(MONGO_PORT)
    MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
else:  # Assumption: The database is stored in mongodb cloud.
    MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}/?retryWrites=true&w=majority&appName=Cluster0"

client = AsyncIOMotorClient(MONGO_URI)
db = client.upcast
contracts_collection = db.contracts  # contracts collection


# varify the user and negotiation
async def _varify_contract(
        contract_id: str
):
    # validate & load contract
    try:
        cid = ObjectId(contract_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid contract id")

    contract = await contracts_collection.find_one({"_id": cid})

    if not contract:
        raise HTTPException(status_code=404, detail="contract not found")

    return contract


@app.post("/contract/create", summary="Create a contract")
async def create_contract(
        body: UpcastContractObject = Body(..., description="The contract object"),
):
    try:

        print("function of /contract/create: contract API body: \n", body.dict())

        contract_obj = pydantic_to_dict(body, clean_id=True)

        contract_type = contract_obj.get("contract_type")

        if contract_type == "dsa":

            print("\naiming to generate a Data Sharing Agreement contract:\n")

            # If cactus_format is truthy, convert ODRL format first
            if normalize_bool(contract_obj.get("cactus_format")):
                try:
                    contract_obj = odrl_formate_convert(contract_obj)
                    print("\nAfter cactus ODRL conversion, contract_obj updated.")
                except Exception:
                    # If the ODRL conversion fails, surface a clear message
                    err = traceback.format_exc()
                    raise HTTPException(
                        status_code=400,
                        detail=f"ODRL cactus conversion failed. Traceback: {err}",
                    )

            legal_contract = get_dsa_contract_text(contract_obj)
            mp_json = get_dsa_contract_json(contract_obj, include_text=False)
            contract_obj['nlp'] = legal_contract

            contract_obj['mp_json'] = mp_json

            # save the contract_obj into the collection
            contract_obj.pop('id', None)  # remove id item
            contract_result = await contracts_collection.insert_one(contract_obj)
            contract_id = contract_result.inserted_id

            client_pid = getattr(body.client_optional_info, "client_pid", None)
            if client_pid:

                print(
                    f"contract {contract_id} created successfully for Negotiation {body.client_optional_info.client_pid}"
                    f" and saved in MongoDB\n\n")

            else:
                print(
                    f"contract {contract_id} created successfully for Negotiation request and saved in MongoDB \n\n")

            return {
                "message": "legal contract created successfully",
                "legal_contract": legal_contract,
                "contract_id": str(contract_id),
            }

        elif contract_type == "pda":

            print("\naiming to generate a consent contract:\n")

            # If cactus_format is truthy, convert ODRL format first
            if normalize_bool(contract_obj.get("cactus_format")):
                try:
                    contract_obj = odrl_formate_convert(contract_obj)
                    print("\nAfter cactus ODRL conversion, contract_obj updated.")
                except Exception:
                    # If the ODRL conversion fails, surface a clear message
                    err = traceback.format_exc()
                    raise HTTPException(
                        status_code=400,
                        detail=f"ODRL cactus conversion failed. Traceback: {err}",
                    )

            legal_contract = get_consent_contract_text(contract_obj)  # text generate

            mp_json = get_ca_contract_json(contract_obj, include_text=False)
            contract_obj['nlp'] = legal_contract

            contract_obj['mp_json'] = mp_json

            # save the contract_obj into the collection
            contract_obj.pop('id', None)  # remove id item
            contract_result = await contracts_collection.insert_one(contract_obj)
            contract_id = contract_result.inserted_id

            client_pid = getattr(body.client_optional_info, "client_pid", None)
            if client_pid:
                print(
                    f"contract {contract_id} created successfully for Consent {body.client_optional_info.client_pid}"
                    f" and saved in MongoDB\n\n")
            else:
                print(
                    f"contract {contract_id} created successfully for Consent request and saved in MongoDB \n\n")

            return {
                "message": "legal contract created successfully",
                "legal_contract": legal_contract,
                "contract_id": str(contract_id),
            }

        else:
            error_message = traceback.format_exc()  # get the full traceback
            raise HTTPException(
                status_code=500,
                detail=f"contract could not be created. Please indiate the contract type. Traceback: {error_message}",
            )

    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(
            status_code=500,
            detail=f"contract could not be created. {str(e)}. Traceback: {error_message}",
        )


#
@app.put("/contract/update/{contract_id}", summary="Update a contract")
async def update_contract(
        contract_id: str = Path(..., description="The ID of the Negotiation"),
        body: UpcastContractObject = Body(..., description="The contract object"),
):
    try:

        # 1. check the current contract
        await _varify_contract(contract_id)

        contract_obj = pydantic_to_dict(body, clean_id=True)
        contract_obj.pop('id', None)  # remove id item

        # update the existing contract
        update_result = await contracts_collection.update_one(
            {"_id": ObjectId(contract_id)}, {"$set": contract_obj}
        )

        if update_result.matched_count == 0:
            raise HTTPException(
                status_code=404,
                detail="Negotiation not found or you do not have permission to update this negotiation",
            )

        if update_result.modified_count == 0:
            raise HTTPException(status_code=400, detail="No changes")

        print(
            f"The contract {contract_id} is updated successfully for Negotiation {body.client_optional_info.client_pid} and saved in MongoDB")

        return {
            "message": "contract updated successfully",
            "contract_id": contract_id,
        }
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(
            status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}"
        )

#
@app.get(
    "/contract/get_request_body/{contract_id}",
    summary="return a request body about a contract",
)
async def get_request_body_for_legal_contract(
        contract_id: str = Path(..., description="The ID of the contract"),
):
    # 1. Validate & convert the ID
    try:
        obj_id = ObjectId(contract_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid contract id format, please try again")

    # 2. Fetch from Mongo
    doc = await contracts_collection.find_one({"_id": obj_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Contract not found")

        # 3) Serialize Mongo types and normalize _id -> id
    encoded = jsonable_encoder(
        doc,
        custom_encoder={
            ObjectId: str,
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat(),
        },
    )
    encoded["id"] = encoded.pop("_id", None)

    # 4) Return as your Pydantic model (note the **)
    return UpcastContractObject(**encoded)



@app.get(
    "/contract/get_contract/{contract_id}",
    summary="Review the legal contract",
)
async def get_legal_contract(
    contract_id: str = Path(..., description="The ID of the contract"),
):
    # 1) Validate & convert the ID
    try:
        obj_id = ObjectId(contract_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid contract id format, please try again")

    # 2) Fetch from Mongo
    doc = await contracts_collection.find_one({"_id": obj_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Contract not found")

    # 3) Ensure the contract text exists (adjust the key if yours is different)
    contract_text = doc.get("nlp", "")  # or doc.get("contract_text", "")
    if not contract_text:
        raise HTTPException(status_code=404, detail="No contract found in the negotiations")

    # 4) Serialize Mongo types and (optionally) rename _id -> id
    encoded = jsonable_encoder(
        doc,
        custom_encoder={
            ObjectId: str,
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat(),
        },
    )


    # add your custom fields
    encoded["contractid"] = encoded.pop("_id", None)

    if encoded.get("contract_type") == "dsa":
        encoded["negotiationid"] = encoded.get("client_optional_info", {}).get("client_pid")

    if encoded.get("contract_type") == "pda":
        encoded["consentid"] = encoded.get("client_optional_info", {}).get("client_pid")

    # drop fields safely
    encoded.pop("mp_json", None)

    # --- move keys to the front ---
    contractid = encoded.pop("contractid", None)
    negotiationid = encoded.pop("negotiationid", None)
    consentid = encoded.pop("consentid", None)

    ordered = {}
    if contractid is not None:
        ordered["contractid"] = contractid
    if negotiationid is not None:
        ordered["negotiationid"] = negotiationid
    if consentid is not None:
        ordered["consentid"] = consentid

    # append the rest preserving their original order
    ordered.update(encoded)

    return ordered




@app.get(
    "/contract/getUpcastContract/{contract_id}",
    summary="Review a machine processable contract",
)
async def get_machine_processable_contract(
    contract_id: str = Path(..., description="The ID of the contract"),
):

    try:
        contract_json = await get_legal_contract(contract_id)
    except HTTPException:
        raise
    except Exception as exc:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Failed to fetch contract: {exc}\n{tb}")

    try:
        contract_json.pop("definitions")
        contract_json.pop("custom_clauses")
        contract_json.pop("dpw")


        ttl_payload = contract_to_turtle(contract_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Failed to convert contract to Turtle: {exc}\n{tb}")

    filename = f"contract_{contract_id}.ttl"
    return Response(
        content=ttl_payload,
        media_type="text/turtle",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    )




@app.put(
    "/contract/sign_contract/{contract_id}",
    summary="Sign a contract",
)
async def sign_contract(
        contract_id: str = Path(..., description="The ID of the contract"),
        body: UpcastSignatureObject = Body(..., description="The signature object"),
):
    try:

        user_role = getattr(body, "user_role")
        sig_val = getattr(body, f"{user_role}_signature")
        sig_date = getattr(body, f"{user_role}_signature_date")

        if sig_val is None:
            raise HTTPException(400, "No signature data provided")

        # build a minimal update document
        update_data = {
            f"{user_role}_signature": sig_val,
            f"{user_role}_signature_date": sig_date,
        }

        print("update signature data: %r", update_data)

        result = await contracts_collection.update_one(
            {"_id": ObjectId(contract_id)},
            {"$set": update_data}
        )

        if result.matched_count == 0:
            raise HTTPException(404, "Negotiation not found or no permission")
        if result.modified_count == 0:
            raise HTTPException(400, "No changes detected")

        print(f"The signature of the contract {contract_id} is updated successfully and saved in MongoDB")

        return {
            "message": "Contract signature updated successfully",
            "contract_id": contract_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"Exception: {e}\n{tb}")


class ContractDiffResponse(BaseModel):
    previous_contract: Dict[str, Any]
    last_contract: Dict[str, Any]
    changes: Dict[str, Any] = Field(..., description="Diff ops between first and last")


@app.get(
    "/contract/get_contract_diffs",
    summary="Get the difference between two contracts",
    response_model=ContractDiffResponse,
)
async def get_diffs_bet_two_contracts(
        response: Response,
        first_contract_id: str = Header(..., alias="first-contract-id", description="ID of the first contract"),
        second_contract_id: str = Header(..., alias="second-contract-id", description="ID of the second contract"),
):
    # 1) Validate ObjectIds
    try:
        first_oid = ObjectId(first_contract_id)
        logger.debug("First contract ObjectId: %s", first_oid)
    except Exception as e:
        logger.error("Invalid first contract ID format: %s, error: %s", first_contract_id, e)
        raise HTTPException(status_code=400, detail=f"Invalid first contract ID format: {first_contract_id}")

    try:
        second_oid = ObjectId(second_contract_id)
        logger.debug("Second contract ObjectId: %s", second_oid)
    except Exception as e:
        logger.error("Invalid second contract ID format: %s, error: %s", second_contract_id, e)
        raise HTTPException(status_code=400, detail=f"Invalid second contract ID format: {second_contract_id}")

    # 2) Fetch both in one go
    try:
        docs = await contracts_collection.find(
            {"_id": {"$in": [first_oid, second_oid]}}
        ).to_list(length=2)
        doc_map = {doc["_id"]: doc for doc in docs}

        # Map correctly: first -> previous/base, second -> last/new
        previous_doc = doc_map.get(first_oid)
        last_doc = doc_map.get(second_oid)

        if not previous_doc or not last_doc:
            missing = []
            if not previous_doc:
                missing.append(f"first ({first_contract_id})")
            if not last_doc:
                missing.append(f"second ({second_contract_id})")
            raise HTTPException(status_code=404, detail=f"Contract not found for: {', '.join(missing)}")

        # 3) Serialize & diff (ensure your pydantic_to_dict accepts plain dicts or adapt)
        previous_dict = pydantic_to_dict(previous_doc, True)
        last_dict = pydantic_to_dict(last_doc, True)

        changes = find_changes(previous_dict, last_dict)

        # 4) Headers & response
        response.headers["X-Changes-Count"] = str(len(changes))
        response.headers["X-Compared-Ids"] = f"{first_contract_id},{second_contract_id}"

        return ContractDiffResponse(
            previous_contract=previous_dict,
            last_contract=last_dict,
            changes=changes,
        )

    except HTTPException:
        # Preserve intended 400/404 responses
        raise
    except Exception as e:
        logger.exception("Error processing contract differences: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error while processing contract differences")


# ----------------------------
# get diff Models
# ----------------------------
class TextDiffRequest(BaseModel):
    first_text: str = Field(..., description="Original text (data consumer draft)")
    second_text: str = Field(..., description="Edited text (data provider changes)")
    normalize_unicode: bool = Field(
        default=True,
        description="If True, apply NFC Unicode normalization to both inputs."
    )


class TextDiffResponse(BaseModel):
    diff_html: str
    change_segments: int
    changes: List[str]
    stats: Dict[str, int]


# ----------------------------
# Core diff helper (word-level, preserves whitespace)
# ----------------------------
_TOKEN_RE = re.compile(r"\w+|[^\w\s]|\s+")


def _tokenize(s: str) -> List[str]:
    return _TOKEN_RE.findall(s)


def _wrap_del(text: str) -> str:
    return f'<span class="del">{escape(text)}</span>'


def _wrap_ins(text: str) -> str:
    return f'<span class="ins">{escape(text)}</span>'


def diff_clauses_html(a: str, b: str):
    """
    Returns (html_snippet, changes_list, stats_dict)
    - html_snippet contains only the diff (no <html> wrapper) so you can drop it into your UI.
    - changes_list has one line per changed segment (insert/delete/replace).
    - stats_dict has token-level counts.
    """
    t1 = _tokenize(a)
    t2 = _tokenize(b)

    sm = SequenceMatcher(a=t1, b=t2, autojunk=False)

    out_parts: List[str] = []
    changes: List[str] = []
    stats = {
        "segments": 0,
        "inserted_tokens": 0,
        "deleted_tokens": 0,
        "replaced_old_tokens": 0,
        "replaced_new_tokens": 0,
    }

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out_parts.append(escape("".join(t1[i1:i2])))
        elif tag == "delete":
            seg_old = "".join(t1[i1:i2])
            out_parts.append(_wrap_del(seg_old))
            stats["segments"] += 1
            stats["deleted_tokens"] += (i2 - i1)
            changes.append(f"Deleted: {seg_old.strip()[:120]}")
        elif tag == "insert":
            seg_new = "".join(t2[j1:j2])
            out_parts.append(_wrap_ins(seg_new))
            stats["segments"] += 1
            stats["inserted_tokens"] += (j2 - j1)
            changes.append(f"Inserted: {seg_new.strip()[:120]}")
        elif tag == "replace":
            seg_old = "".join(t1[i1:i2])
            seg_new = "".join(t2[j1:j2])
            out_parts.append(_wrap_del(seg_old))
            out_parts.append(_wrap_ins(seg_new))
            stats["segments"] += 1
            stats["replaced_old_tokens"] += (i2 - i1)
            stats["replaced_new_tokens"] += (j2 - j1)
            changes.append(f"Replaced: {seg_old.strip()[:120]}  →  {seg_new.strip()[:120]}")

    html_body = "".join(out_parts)

    # Minimal CSS classes you can include once in your page/app stylesheet
    # .del { background: #ffecec; text-decoration: line-through; }
    # .ins { background: #eaffea; text-decoration: underline; }
    return html_body, changes, stats


@app.post("/contract/get_text_diffs", response_model=TextDiffResponse,
          summary="Get HTML diff and change counts for two text")
def get_diff_for_clauses(req: TextDiffRequest) -> TextDiffResponse:
    a = req.first_text or ""

    b = req.second_text or ""

    if req.normalize_unicode:
        a = unicodedata.normalize("NFC", a)
        b = unicodedata.normalize("NFC", b)

    diff_html, changes, stats = diff_clauses_html(a, b)

    # You can add a small legend header here if you want it bundled:
    legend = (
        '<div class="legend" style="margin-bottom:8px; font-size:0.9rem;">'
        '<span class="del" style="padding:1px 4px; border-radius:4px;">Deleted</span> '
        '<span class="ins" style="padding:1px 4px; border-radius:4px;">Inserted</span>'
        "</div>"
    )
    # Return just the snippet + legend (no full HTML document)
    snippet = legend + f'<div class="diff" style="white-space: pre-wrap;">{diff_html}</div>'

    return TextDiffResponse(
        diff_html=snippet,
        change_segments=stats["segments"],
        changes=changes,
        stats=stats
    )


@app.get(
    "/contract/download/{contract_id}",
    summary="Download the legal contract",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            "description": "The negotiation contract as a PDF file",
        }
    },
)
async def download_contract(
        contract_id: str = Path(..., description="The ID of the contract"),
):
    try:

        contract = await contracts_collection.find_one({"_id": ObjectId(contract_id), })
        if not contract:
            raise HTTPException(status_code=404, detail="contract not found")

        # obtain textual infor from contract collection
        contract_text = contract.get("nlp", "")
        contract_type = contract.get("contract_type")

        print("contract_type: ", contract_type)

        if not contract_text:
            raise HTTPException(
                status_code=404, detail="No contract found in the negotiations"
            )

        negotiation_id = contract.get('negotiation_id')

        # write the text to the PDF
        pdf_buffer = text_to_pdf_bytes(contract_text,
                                       contract_id,
                                       negotiation_id,
                                       contract.get('consumer_signature', ''),
                                       contract.get('consumer_signature_date', ''),
                                       contract.get('provider_signature', ''),
                                       contract.get('provider_signature_date', ''),
                                       contract_type,
                                       add_signature_block=True)

        if negotiation_id:

            return_name = f"contract_{contract_id}_for_negotiation-'f'{negotiation_id}.pdf"
        else:
            return_name = f"contract_{contract_id}.pdf"

        return StreamingResponse(
            content=pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'inline; filename={return_name}'
                ),
                "Content-Type": 'application/octet-stream'
            },
        )

    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(
            status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}"
        )

#
# @app.get(
#     "/contract/download_machine_processable_file/{contract_id}",
#     summary="Download a machine processable contract",
# )
# async def download_machine_processable_contract(
#         contract_id: str = Path(..., description="The ID of the contract"),
# ):
#     try:
#         # Fetch the contract doc
#         doc = await contracts_collection.find_one({"_id": ObjectId(contract_id)})
#         if not doc:
#             raise HTTPException(status_code=404, detail="Contract not found")
#
#         # Pull machine-processable JSON payload
#         mp_json = doc.get("mp_json")
#         mp_json["full_text"] = doc.get("nlp")
#         if mp_json in (None, "", {}):
#             raise HTTPException(status_code=404, detail="No machine-processable JSON found for this contract")
#
#         # Figure out a friendly filename
#         negotiation_id = doc.get("negotiation_id")
#         if negotiation_id:
#             filename = f"contract_{contract_id}_for_negotiation-{negotiation_id}.json"
#         else:
#             filename = f"contract_{contract_id}.json"
#
#         # Serialize to bytes
#         payload_bytes = _to_bytes(mp_json)
#
#         # Stream the file with attachment headers
#         return StreamingResponse(
#             iter([payload_bytes]),
#             media_type="application/json",
#             headers={
#                 "Content-Disposition": f'attachment; filename="{filename}"'
#             },
#         )
#
#     except HTTPException:
#         # Re-raise clean HTTP errors
#         raise
#     except BaseException as e:
#         error_message = traceback.format_exc()
#         raise HTTPException(
#             status_code=500,
#             detail=f"Exception: {str(e)}. Traceback: {error_message}",
#         )


# search a contract by a string (matedata)
class SearchResult(BaseModel):
    contract_id: str  # stringified ObjectId
    score: Optional[
        float] = None  # Higher = better match for that specific query (influenced by term frequency and your field weights in the text index).
    snippet: Optional[str] = None  # short clause match
    base_info: Optional[Dict[str, Any]] = None


class SearchResponse(BaseModel):
    total: int
    results: List[SearchResult]


async def ensure_indexes():
    # Create a multi-field text index for fast $text queries (if not present)
    # Weights bump fields like title & tags.
    existing = await contracts_collection.index_information()
    if not any(v.get("key") == [("$$**", "text")] for v in existing.values()):
        # Fallback: create a named text index across known fields
        await contracts_collection.create_index(
            [(f, TEXT) for f in TEXT_FIELDS],
            name="search_text_idx",
            default_language="english",
            weights={
                "base_info.resource_description.title": 8,
                "base_info.resource_description.tags": 6,
                "nlp": 2,
            },
        )
    # Nice to have: an index for created/updated sorting if you add it
    await contracts_collection.create_index([("updated_at", ASCENDING)], name="updated_at_idx")


@app.get("/contract/search", response_model=SearchResponse,
         summary="Search contracts by metadata/clauses (no pagination)")
async def search_contract(
        keywords: str = Query(..., description="Search string (metadata, clauses, ODRL, contacts, etc.)")
):
    q = keywords
    await ensure_indexes()

    # Prefer MongoDB text search, fall back to regex across TEXT_FIELDS
    query = {"$text": {"$search": q}}
    projection = {
        "base_info": 1,
        "nlp": 1,
        "score": {"$meta": "textScore"},
    }

    try:
        total = await contracts_collection.count_documents(query)
        cursor = contracts_collection.find(query, projection=projection).sort([("score", {"$meta": "textScore"})])
    except Exception:
        query = regex_or_query(q)  # case-insensitive OR across TEXT_FIELDS
        total = await contracts_collection.count_documents(query)
        cursor = contracts_collection.find(query, projection={"base_info": 1, "nlp": 1})

    # Build lightweight snippets from `nlp`
    rx = re.compile(re.escape(q), re.IGNORECASE)
    results = []
    async for doc in cursor:
        snippet = None
        nlp_text = doc.get("nlp")
        if isinstance(nlp_text, str):
            m = rx.search(nlp_text)
            if m:
                start = max(0, m.start() - 80)
                end = min(len(nlp_text), m.end() + 80)
                snippet = ("..." if start > 0 else "") + nlp_text[start:end] + ("..." if end < len(nlp_text) else "")

        results.append({
            "contract_id": str(doc["_id"]),  # include contract id
            "score": float(doc.get("score", 0)) if isinstance(doc.get("score"), (int, float)) else None,
            "snippet": snippet,
            "base_info": doc.get("base_info"),
        })

    return SearchResponse(total=total, results=results)


@app.get(
    "/contract/contract_summary/{contract_id}",
    summary="Get a summary of the contract",
)
async def get_summary_for_contract(
        contract_id: str = Path(..., description="The ID of the contract"),
        max_words: int = Query(
            500,
            ge=200,
            le=2000,
            description="Approximate number of WORDS for the summary (not tokens).",
        ),
):
    # 1) Validate & convert the ID
    try:
        obj_id = ObjectId(contract_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid contract id format, please try again")

    # 2) Fetch from Mongo
    contract = await contracts_collection.find_one({"_id": obj_id})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # 3) Pull NL text
    contract_text = (contract.get("nlp") or "").strip()
    if not contract_text:
        raise HTTPException(
            status_code=422,
            detail="No natural-language text found for this contract (expected non-empty 'nlp' field).",
        )

    # 4) Summarize
    try:
        # If your summarize function is synchronous:
        summary = summarize_text(contract_text, max_words=max_words)

        # If it's async instead, use:
        # summary = await summarize_text(contract_text, max_words=max_words)

    except Exception as e:
        # Common causes: missing OPENAI_API_KEY, network/timeout, rate limiting
        raise HTTPException(status_code=502, detail=f"Failed to generate summary: {e}")

    # 5) Return
    return JSONResponse(
        {
            "contract_id": contract_id,
            "summary_words_target": max_words,
            "summary": summary,
            "length_chars": len(contract_text),
            "source_field": "nlp",
        }
    )


@app.get(
    "/contract/odrl_translation",
    summary="translate an ODRL into natural language"
)
async def odrl_translation(
        body: Dict[str, Any] = Body(..., description="request body"),
):
    odrl_dic = body
    definitions = {}
    odrl_summary = create_odrl_decription(odrl_dic, definitions)

    return {"definitions": definitions, "odrl_des": odrl_summary}


# Recursive function to find changes in nested dictionaries
def find_changes(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    changes = {}
    excluded_keys = {"id", "_id", "type", "uid", "created_at", "updated_at"}

    if len(old) == 0:
        return changes

    for key in new:
        if key in excluded_keys:
            continue
        if key in old:
            if isinstance(new[key], dict) and isinstance(old[key], dict):
                sub_changes = find_changes(old[key], new[key])
                if sub_changes:
                    changes[key] = sub_changes
            elif new[key] != old[key]:
                changes[key] = {"from": old[key], "to": new[key]}
        else:
            changes[key] = {"from": None, "to": new[key]}

    for key in old:
        if key in excluded_keys:
            continue
        if key not in new:
            changes[key] = {"from": old[key], "to": None}

    return changes


@app.delete("/contract/delete/{contract_id}",
            summary="Delete a contract")
async def delete_contracts_for_negotiation(
        contract_id: str = Path(..., description="The ID of the negotiation"),
):
    # 1. Convert and verify the contract exists
    try:
        oid = ObjectId(contract_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid contract ID format!!")

    contract = await contracts_collection.find_one({"_id": oid})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # 2. Delete the contract document
    result = await contracts_collection.delete_one({"_id": oid})
    if result.deleted_count == 0:
        # Shouldn’t really happen since we just fetched it, but just in case
        raise HTTPException(status_code=500, detail="Failed to delete contract")

    # 4. Return confirmation
    return {"detail": f"Contract {contract_id} deleted successfully"}


if __name__ == "__main__":
    import uvicorn

    # changed the 127.0.0.1 with "0.0.0.0"
    uvicorn.run(app, host="0.0.0.0", port=8866)
