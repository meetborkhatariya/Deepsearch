from typing import Optional, Dict, List
from fastapi import APIRouter, HTTPException, FastAPI, Request, Response, UploadFile, File as FastAPIFile, Form, Query
from fastapi.responses import JSONResponse
from http import HTTPStatus
from datetime import datetime, timezone, timedelta
import uuid
import asyncio
import json
import sqlite3
import os
import hashlib
import hmac
import secrets
import base64
from contextlib import contextmanager
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from .deep_researcher import (
    run_researcher_from_data,
    format_previous_summaries_for_context,
    create_structured_summary,
    format_lab_data_toon,
    estimate_tokens,
    ensure_json_safe,
    deep_researcher
)

from .prompts import final_report_generation_prompt

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.callbacks.base import BaseCallbackHandler

from .db_chroma import (
    get_user_summaries, 
    get_summary_by_date, 
    get_parameter_history,
    get_summaries_by_date_range,
    init_db,
    save_summary
)

from . import db_reports

from .voice_service import generate_health_voice_insight
from .pdf_to_json import extract_lab_json_from_pdf, extract_text_from_pdf

# ---- SQLite Database Setup ----

# Use canonical DB path under app/db to avoid creating DB in project root
DB_PATH = Path(__file__).resolve().parent / "db" / "deep_research_transactions.db"
SESSION_COOKIE_NAME = "health_session"
SESSION_TTL_DAYS = 7


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_password_salt() -> str:
    return secrets.token_hex(16)


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 150000)
    return base64.b64encode(digest).decode("utf-8")


def _verify_password(password: str, salt: str, stored_hash: str) -> bool:
    candidate_hash = _hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, stored_hash)


def _generate_session_token() -> str:
    return secrets.token_urlsafe(48)

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    # Ensure parent directory exists before opening connection
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_transaction_db():
    """Initialize the transactions table.

    This function is migration-safe: if a `transactions` table already exists but
    lacks expected columns (e.g. `user_id`), it will add them using `ALTER TABLE`.
    This prevents import-time failures when older DBs with different schemas are present.
    """
    # Ensure DB dir exists and then inspect/migrate schema as needed
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Log the absolute path to verify database location
    db_abs_path = DB_PATH.absolute()

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    # Enable WAL mode for better concurrency and durability
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")  # Ensure data is written to disk
    
    cursor = conn.cursor()
    try:
        # If table does not exist, create it with the full schema
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
        table_exists = cursor.fetchone()
        
        if not table_exists:
            cursor.execute("""
                CREATE TABLE transactions (
                    txn_id TEXT PRIMARY KEY,
                    report_id TEXT,
                    user_id TEXT,
                    lab_parameter TEXT,
                    status TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    cost_estimate_usd REAL,
                    cost_estimate_inr REAL,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON transactions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON transactions(status)")
            conn.commit()
        else:            
            # Table exists: check columns and add any missing ones
            cursor.execute("PRAGMA table_info(transactions)")
            existing_cols = {row[1] for row in cursor.fetchall()}  # name is at index 1

            # Expected columns and their SQL types (for ALTER TABLE ADD COLUMN)
            expected_columns = {
                "txn_id": "TEXT",
                "report_id": "TEXT",
                "user_id": "TEXT",
                "lab_parameter": "TEXT",
                "status": "TEXT",
                "started_at": "TEXT",
                "completed_at": "TEXT",
                "result_json": "TEXT",
                "cost_estimate_usd": "REAL",
                "cost_estimate_inr": "REAL",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            }

            for col, col_type in expected_columns.items():
                if col not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE transactions ADD COLUMN {col} {col_type}")
                    except Exception as e:
                        # Best-effort: keep startup resilient while exposing migration issues.
                        print(f"Warning: failed to add transactions.{col}: {e}")

            # Ensure indexes exist
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON transactions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON transactions(status)")
            conn.commit()
        
        # Verify record count
        cursor.execute("SELECT COUNT(*) FROM transactions")
        count = cursor.fetchone()[0]

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at)")

        # ── Health profile table ──
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_health_profiles (
                user_id TEXT PRIMARY KEY,
                -- personal details
                height_cm REAL,
                weight_kg REAL,
                age INTEGER,
                gender TEXT,
                -- health goals
                health_goal TEXT,
                -- personal health info
                blood_group TEXT,
                allergies TEXT,
                chronic_conditions TEXT,
                smoking TEXT DEFAULT 'no',
                alcohol TEXT DEFAULT 'no',
                diet_type TEXT DEFAULT 'non-veg',
                health_history TEXT,
                surgeries TEXT,
                -- timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_user(name: str, email: str, password: str) -> dict:
    email_normalized = email.strip().lower()
    now = _utc_now_iso()
    user_id = str(uuid.uuid4())
    salt = _generate_password_salt()
    password_hash = _hash_password(password, salt)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE email = ?", (email_normalized,))
        if cursor.fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists.")

        cursor.execute(
            """
            INSERT INTO users (user_id, name, email, password_hash, password_salt, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name.strip(), email_normalized, password_hash, salt, now, now),
        )

    return {"user_id": user_id, "name": name.strip(), "email": email_normalized}


def _get_user_by_email(email: str) -> Optional[dict]:
    email_normalized = email.strip().lower()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ? LIMIT 1", (email_normalized,))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def _get_user_by_id(user_id: str) -> Optional[dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ? LIMIT 1", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def _create_session(user_id: str) -> str:
    token = _generate_session_token()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=SESSION_TTL_DAYS)).isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO auth_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires_at),
        )
    return token


def _delete_session(token: str) -> None:
    if not token:
        return
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))


def _extract_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "", 1).strip()
    return None


def _resolve_session_token(request: Request) -> Optional[str]:
    return _extract_bearer_token(request) or request.cookies.get(SESSION_COOKIE_NAME)


def _get_session_user(request: Request) -> Optional[dict]:
    token = _resolve_session_token(request)
    if not token:
        return None

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM auth_sessions WHERE token = ? LIMIT 1", (token,))
        session_row = cursor.fetchone()
        if not session_row:
            return None

        expires_at = session_row["expires_at"]
        if expires_at < _utc_now_iso():
            cursor.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            return None

        cursor.execute("SELECT user_id, name, email FROM users WHERE user_id = ? LIMIT 1", (session_row["user_id"],))
        user_row = cursor.fetchone()
        if not user_row:
            return None
        return dict(user_row)
        
def save_transaction_to_db(txn_data: dict):
    """Save or update transaction in SQLite"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        now = datetime.now(timezone.utc).isoformat()
        result = txn_data.get("result")
        result_json = json.dumps(result) if result else None
        
        # Safely extract cost estimates
        cost_usd = None
        cost_inr = None
        if result and isinstance(result, dict):
            cost_usd = result.get("cost_estimate_usd")
            cost_inr = result.get("cost_estimate_inr")
        
        cursor.execute("""
            INSERT OR REPLACE INTO transactions 
            (txn_id, report_id, user_id, lab_parameter, status, started_at, completed_at, 
             result_json, cost_estimate_usd, cost_estimate_inr, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
                    COALESCE((SELECT created_at FROM transactions WHERE txn_id = ?), ?), ?)
        """, (
            txn_data["txn_id"],
            txn_data.get("report_id"),
            txn_data["user_id"],
            txn_data["lab_parameter"],
            txn_data["status"],
            txn_data["started_at"],
            txn_data.get("completed_at"),
            result_json,
            cost_usd,
            cost_inr,
            txn_data["txn_id"],  # for COALESCE
            now,  # for created_at if new
            now   # for updated_at
        ))

def get_transaction_from_db(txn_id: str) -> Optional[dict]:
    """Retrieve transaction from SQLite"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM transactions WHERE txn_id = ?
        """, (txn_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            "txn_id": row["txn_id"],
            "report_id": row["report_id"],
            "user_id": row["user_id"],
            "lab_parameter": row["lab_parameter"],
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

def get_user_transactions(user_id: str, limit: int = 50) -> List[dict]:
    """Get all transactions for a user"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM transactions 
            WHERE user_id = ? 
            ORDER BY started_at DESC 
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        return [
            {
                "txn_id": row["txn_id"],
                "report_id": row["report_id"],
                "user_id": row["user_id"],
                "lab_parameter": row["lab_parameter"],
                "status": row["status"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
            for row in rows
        ]


def find_transaction_by_user_and_date(user_id: str, report_date: str) -> Optional[dict]:
    """Search transactions table for a transaction matching user_id and report_date."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT txn_id, status, started_at, completed_at, result_json FROM transactions WHERE user_id = ? ORDER BY started_at DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        for row in rows:
            result_json = row["result_json"]
            if not result_json:
                continue
            try:
                data = json.loads(result_json)
            except Exception:
                continue

            # Match by normalized report_date if available in stored result
            stored_date = data.get("report_date")
            if stored_date == report_date:
                # include report_id if stored in the result JSON
                report_id_val = data.get("report_id") or data.get("reportId")
                return {
                    "txn_id": row["txn_id"],
                    "report_id": report_id_val,
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"]
                }

    return None


def get_transaction_by_report_id(report_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Retrieve a transaction row by its stored report_id and optionally user_id."""
    if not report_id:
        return None
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if user_id:
            # Query by both report_id and user_id for exact match
            cursor.execute(
                "SELECT * FROM transactions WHERE report_id = ? AND user_id = ? LIMIT 1",
                (report_id, user_id)
            )
        else:
            # Fallback to report_id only
            cursor.execute(
                "SELECT * FROM transactions WHERE report_id = ? LIMIT 1",
                (report_id,)
            )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "txn_id": row["txn_id"],
            "report_id": row["report_id"],
            "user_id": row["user_id"],
            "lab_parameter": row["lab_parameter"],
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

# Initialize both databases on startup
init_transaction_db()
init_db()

app = FastAPI()

# Keep in-memory cache for quick access during processing
# Also persist to SQLite for durability
transaction_cache = {}

# Initialize SQLite database
try:
    db_reports.init_db()
    print("✓ SQLite reports database initialized")
except Exception as e:
    print(f"SQLite will initialize on first use: {e}")

router = APIRouter()

# ---- Schemas ----

class ParameterValueSchema(BaseModel):
    value: str
    date: str
    unit: str

class LinkedParameterSchema(BaseModel):
    name: str
    normalRange: Optional[str] = None  # e.g., "40 - 60" or "0.1 - 200"
    currentValues: List[ParameterValueSchema] 
    previousValues: Optional[List[ParameterValueSchema]] = []  

class LabParameterSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())
    user_id: str
    parameterName: str
    currentValue: str
    reportDate: str  
    # accept both `report_id` and `reportId` from JSON
    report_id: Optional[str] = Field(None, alias="reportId")
    previousValues: Optional[List[ParameterValueSchema]] = None
    linkedParameters: Optional[Dict[str, LinkedParameterSchema]] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    chronicCondition: Optional[List[str]] = None
    bmi: Optional[float] = None
    steps: Optional[Dict[str, Optional[int]]] = None
    language: Optional[str] = Field(default="english", description="Language for voice generation: 'english', 'hindi', or 'gujarati'")
    model: Optional[str] = Field(
        default="openai",
        description="AI model strategy (Tavily search runs for ALL models): "
                    "'all' = OpenAI + KB + Tavily (supervisor: OpenAI), "
                    "'openai' = OpenAI + Tavily (default)"
    )


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/signup")
async def signup(request: SignupRequest, response: Response):
    if not request.name or len(request.name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
    if not request.email or "@" not in request.email:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if not request.password or len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    user = _create_user(request.name, request.email, request.password)
    token = _create_session(user["user_id"])
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
    )

    return {
        "status": "success",
        "token": token,
        "user": {
            "id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
        },
    }


@router.post("/auth/login")
async def login(request: LoginRequest, response: Response):
    user = _get_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not _verify_password(request.password, user["password_salt"], user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = _create_session(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE user_id = ?", (_utc_now_iso(), _utc_now_iso(), user["user_id"]))

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
    )

    return {
        "status": "success",
        "token": token,
        "user": {
            "id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
        },
    }


@router.get("/auth/me")
async def auth_me(request: Request):
    user = _get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "status": "success",
        "user": {
            "id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
        },
    }


@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = _resolve_session_token(request)
    _delete_session(token or "")
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success", "message": "Logged out"}


# ─── Health Profile ──────────────────────────────────────────────────────────

class HealthProfileUpdate(BaseModel):
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    health_goal: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    smoking: Optional[str] = None
    alcohol: Optional[str] = None
    diet_type: Optional[str] = None
    health_history: Optional[str] = None
    surgeries: Optional[str] = None


@router.get("/health-profile/{user_id}")
async def get_health_profile(user_id: str, request: Request):
    session_user = _get_session_user(request)
    if not session_user or session_user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_health_profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return {"status": "success", "profile": None}
        return {"status": "success", "profile": dict(row)}


@router.put("/health-profile/{user_id}")
async def upsert_health_profile(user_id: str, body: HealthProfileUpdate, request: Request):
    session_user = _get_session_user(request)
    if not session_user or session_user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    now = _utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM user_health_profiles WHERE user_id = ?", (user_id,))
        exists = cursor.fetchone() is not None
        if exists:
            cursor.execute(
                """
                UPDATE user_health_profiles SET
                    height_cm=?, weight_kg=?, age=?, gender=?,
                    health_goal=?,
                    blood_group=?, allergies=?, chronic_conditions=?,
                    smoking=?, alcohol=?, diet_type=?,
                    health_history=?, surgeries=?,
                    updated_at=?
                WHERE user_id=?
                """,
                (
                    body.height_cm, body.weight_kg, body.age, body.gender,
                    body.health_goal,
                    body.blood_group, body.allergies, body.chronic_conditions,
                    body.smoking, body.alcohol, body.diet_type,
                    body.health_history, body.surgeries,
                    now, user_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO user_health_profiles
                    (user_id, height_cm, weight_kg, age, gender,
                     health_goal,
                     blood_group, allergies, chronic_conditions,
                     smoking, alcohol, diet_type,
                     health_history, surgeries,
                     created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    user_id,
                    body.height_cm, body.weight_kg, body.age, body.gender,
                    body.health_goal,
                    body.blood_group, body.allergies, body.chronic_conditions,
                    body.smoking, body.alcohol, body.diet_type,
                    body.health_history, body.surgeries,
                    now, now,
                ),
            )
    return {"status": "success", "message": "Health profile saved"}

class TokenTracker:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage):
        if not usage:
            return
        self.input_tokens += usage.get("prompt_tokens", 0)
        self.output_tokens += usage.get("completion_tokens", 0)

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

class TokenTrackingCallback(BaseCallbackHandler):
    def __init__(self, token_tracker: TokenTracker):
        self.token_tracker = token_tracker

    def on_llm_end(self, response, **kwargs):
        llm_output = getattr(response, "llm_output", None)
        if not llm_output:
            print("[DEBUG][LLM_END] No llm_output")
            return

        usage = None

        if "token_usage" in llm_output:
            usage = llm_output["token_usage"]

        elif "usage" in llm_output:
            usage = llm_output["usage"]

        elif "response_metadata" in llm_output:
            usage = llm_output["response_metadata"].get("token_usage")

        print("[DEBUG][LLM_END] llm_output:", llm_output)

        if not usage:
            print("[DEBUG][LLM_END] No token usage found")
            return

        self.token_tracker.add({
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        })

# ---- Consolidated Endpoints ----

@router.post("/lab_parameters")
async def upload_lab_report(lab_data: LabParameterSchema):
    """
    Universal endpoint for uploading lab reports - automatically detects if user is new or follow-up.

    Accepts JSON (smart quotes are normalized by middleware).

    Returns:
        Complete analysis results with status
    """
    if not lab_data.user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    
    if not lab_data.reportDate:
        raise HTTPException(status_code=400, detail="reportDate is required.")
    
    # Normalize report date
    report_date = normalize_report_date(lab_data.reportDate)
    
    # If caller provided a report_id, check for an existing transaction by report_id first.
    # SMART DEDUPLICATION: Also check if the input data has changed (different values for same reportId)
    provided_report_id = getattr(lab_data, "report_id", None)
    if provided_report_id:
        # Compute hash of current input data
        current_hash = compute_lab_data_hash(lab_data.model_dump())
        print(f"[DEDUP] Current input hash: {current_hash}")
        
        # First check in-memory cache for a matching transaction for this user + report_id
        existing_txn = None
        for t in transaction_cache.values():
            if t.get("report_id") == provided_report_id and t.get("user_id") == lab_data.user_id:
                existing_txn = t
                break

        # If not in cache, check DB
        if not existing_txn:
            db_txn = get_transaction_by_report_id(provided_report_id, lab_data.user_id)
            if db_txn and db_txn.get("user_id") == lab_data.user_id:
                existing_txn = db_txn

        if existing_txn:
            # Check if the data has changed by comparing hashes
            stored_result = existing_txn.get("result", {})
            stored_hash = stored_result.get("input_data_hash") if isinstance(stored_result, dict) else None
            
            # Determine if we should use cached result
            should_use_cache = False
            
            if stored_hash is None:
                # No hash stored (old report) - assume data might have changed, process new analysis
                print(f"[DEDUP] No hash in stored result - processing new analysis to be safe")
                should_use_cache = False
            elif stored_hash == current_hash:
                # Hash matches exactly - data is identical, use cached result
                print(f"[DEDUP] Data unchanged (hash match: {stored_hash}). Returning cached result.")
                should_use_cache = True
            else:
                # Hash mismatch - data has changed, process new analysis
                print(f"[DEDUP] Data changed (hash mismatch: {stored_hash} vs {current_hash}). Processing new analysis.")
                should_use_cache = False
            
            if should_use_cache:
                return JSONResponse(
                    content={
                        "txn_id": existing_txn.get("txn_id"),
                        "reportId": existing_txn.get("report_id"),
                        "status": existing_txn.get("status"),
                        "isFirstTime": False,
                        "message": "Report already generated for this reportId with identical values.",
                        "data_hash": stored_hash,
                        "started_at": existing_txn.get("started_at"),
                        "completed_at": existing_txn.get("completed_at")
                    },
                    status_code=HTTPStatus.OK,
                )
            # else: fall through to process new analysis below

    # Check for duplicate reports for same date only when no report_id provided.
    existing_report = get_summary_by_date(lab_data.user_id, report_date)
    if existing_report and not provided_report_id:
        # Try to find the matching transaction in SQLite by user + date
        matched_txn = find_transaction_by_user_and_date(lab_data.user_id, report_date)
        txn_id_to_return = None
        txn_status = "UNKNOWN"
        started_at = None
        completed_at = None

        if matched_txn:
            txn_id_to_return = matched_txn.get("txn_id")
            txn_status = matched_txn.get("status")
            started_at = matched_txn.get("started_at")
            completed_at = matched_txn.get("completed_at")
            report_id_to_return = matched_txn.get("report_id")
        else:
            # Fallback to any identifier present in the summary (e.g., point id)
            txn_id_to_return = existing_report.get("txn_id") or existing_report.get("id") or existing_report.get("point_id")

        # Try to get report id from existing_report as fallback
        if 'report_id_to_return' not in locals():
            report_id_to_return = existing_report.get("report_id") or existing_report.get("reportId")

        return JSONResponse(
            content={
                "txn_id": txn_id_to_return,
                "status": "SUCCESS",
                "reportId": report_id_to_return,
                "isFirstTime": False,
                "actual_txn_status": txn_status,
                "message": f"Report already exists for user {lab_data.user_id} on {report_date}",
                "started_at": started_at,
                "completed_at": completed_at,
            },
            status_code=HTTPStatus.OK,
        )
    
    # Check if this is a new user or follow-up
    previous_summaries = get_user_summaries(lab_data.user_id, limit=1)
    is_new_user = len(previous_summaries) == 0
    
    # Create transaction. Always generate a new txn_id; store provided report_id if present.
    txn_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)
    
    # Compute and store input data hash for smart deduplication
    input_data_hash = compute_lab_data_hash(lab_data.model_dump())
    
    txn_data = {
        "txn_id": txn_id,
        "status": "PENDING",
        "report_id": provided_report_id,
        "is_first_time": True,
        "user_id": lab_data.user_id,
        "lab_parameter": lab_data.parameterName,
        "input_data_hash": input_data_hash,
        "started_at": start_time.isoformat(),
        "completed_at": None,
        "result": None,
    }
    
    transaction_cache[txn_id] = txn_data
    save_transaction_to_db(txn_data)
    
    print(f"[NEW TRANSACTION] txn_id={txn_id}, report_id={provided_report_id}, hash={input_data_hash}")
    
    # Define background processing function
    async def process_lab_report_task():
        """Background task to process lab report"""
        try:
            await process_universal_report(
                txn_id, 
                lab_data.model_dump(),
                report_date,
                is_new_user,
                lab_data.model,
                input_data_hash
            )
            print(f"✅ Lab report processing completed for txn_id={txn_id}")
        except Exception as e:
            print(f"❌ Lab report processing failed for txn_id={txn_id}: {e}")
            # Update transaction status to FAILED
            txn_data_update = {
                "txn_id": txn_id,
                "status": "FAILED",
                "report_id": provided_report_id,
                "user_id": lab_data.user_id,
                "lab_parameter": lab_data.parameterName,
                "started_at": start_time.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result": {
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            }
            transaction_cache[txn_id].update(txn_data_update)
            save_transaction_to_db(txn_data_update)
    
    # Start background processing (fire and forget)
    asyncio.create_task(process_lab_report_task())
    
    # Return immediately with transaction ID
    return JSONResponse(
        content={
            "txn_id": txn_id,
            "status": "PENDING",
            "reportId": provided_report_id,
            "isFirstTime": is_new_user,
            "user_id": lab_data.user_id,
            "report_date": report_date,
            "user_type": "new_user" if is_new_user else "existing_user",
            "previous_reports_count": len(previous_summaries),
            "parameter_name": lab_data.parameterName,
            "started_at": start_time.isoformat()
        },
        status_code=HTTPStatus.ACCEPTED,
    )


@router.get("/lab_parameters/status/{txn_id}")
async def get_report_status(txn_id: str):
    """
    Check the status of a lab report processing request.
    
    Returns the full analysis when completed, including:
    - Report type (new user vs follow-up)
    - Summary and detailed insights
    - Cost breakdown
    - Structured parameter data
    
    Args:
        txn_id: Transaction ID from upload endpoint
        
    Returns:
        Complete report status and results
    """
    # Try cache first, then database
    txn = transaction_cache.get(txn_id)
    if not txn:
        txn = get_transaction_from_db(txn_id)
    
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    result = txn.get("result") or {}
    cost_usd = result.get("cost_estimate_usd", 0.0)
    cost_inr = result.get("cost_estimate_inr", 0.0)
    
    status = txn.get("status", "PENDING")
    
    if status == "PENDING":
        return {
            "txn_id": txn_id,
            "status": status,
            "message": "Report processing in progress...",
            "reportId": txn.get("report_id"),
            "isFirstTime": txn.get("is_first_time", False),
            "started_at": txn.get("started_at")
        }
    elif status == "FAILED":
        return {
            "txn_id": txn_id,
            "status": status,
            "error": result.get("error", "Unknown error"),
            "error_type": result.get("error_type"),
            "reportId": txn.get("report_id"),
            "isFirstTime": txn.get("is_first_time", False),
            "started_at": txn.get("started_at"),
            "completed_at": txn.get("completed_at")
        }
    else:
        return {
            "txn_id": txn_id,
            "status": status,
            "reportId": result.get("reportId") or result.get("report_id"),
            "user_id": result.get("user_id"),
            "report_date": result.get("report_date"),
            "report_type": result.get("report_type"),
            "user_type": result.get("user_type"),
            "previous_reports_count": result.get("previous_reports_count", 0),
            "has_comparison_data": result.get("has_comparison_data", False),
            "started_at": txn.get("started_at"),
            "completed_at": txn.get("completed_at"),
            "summary": result.get("summary"),
            "full_analysis": result.get("final_result"),
            "structured_summary": result.get("structured_summary"),
            "voice_explanation": result.get("voice_explanation"),
            "cost_estimate": {
                "usd": round(cost_usd, 6),
                "inr": round(cost_inr, 4)
            }
        }


@router.get("/users/{user_id}/transactions")
async def list_user_transactions(user_id: str, request: Request, limit: int = Query(default=50, ge=1, le=200)):
    session_user = _get_session_user(request)
    if session_user and session_user.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden for this user account")

    transactions = get_user_transactions(user_id=user_id, limit=limit)
    payload = []
    for txn in transactions:
        result = txn.get("result") or {}
        payload.append(
            {
                "txn_id": txn.get("txn_id"),
                "report_id": txn.get("report_id"),
                "status": txn.get("status"),
                "started_at": txn.get("started_at"),
                "completed_at": txn.get("completed_at"),
                "parameter_name": txn.get("lab_parameter"),
                "summary": result.get("summary"),
                "full_analysis": result.get("final_result"),
                "structured_summary": result.get("structured_summary"),
                "voice_explanation": result.get("voice_explanation"),
                "report_date": result.get("report_date"),
            }
        )

    return {
        "status": "success",
        "count": len(payload),
        "transactions": payload,
    }

# ---- PDF-to-JSON Endpoints ----

@router.post("/pdf_to_lab_json")
async def pdf_to_lab_json(
    file: UploadFile = FastAPIFile(..., description="Digitized PDF lab report"),
    user_id: str = Form(default="", description="User identifier (optional)"),
):
    """Upload a digitized PDF and get the exact LabParameterSchema JSON.

    The returned JSON can be posted directly to ``/api/v1/lab_parameters``
    to trigger the deep research pipeline.

    Accepts:
        - multipart/form-data with field ``file`` (PDF bytes)

    Form fields:
        - user_id (optional): Pre-fill the user_id field in the output JSON.

    Returns:
        JSON matching LabParameterSchema.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="No PDF file provided or file is empty.")

    try:
        result = await extract_lab_json_from_pdf(file_bytes, user_id=user_id)
        return JSONResponse(content=result, status_code=HTTPStatus.OK)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")


@router.post("/upload_pdf_report")
async def upload_pdf_report(
    file: UploadFile = FastAPIFile(..., description="Digitized PDF lab report"),
    user_id: str = Form(..., description="User identifier"),
    language: str = Form(default="english", description="Response language"),
    model: str = Form(default="openai", description="AI model strategy"),
):
    """Upload a PDF lab report → extract parameters → trigger deep research.

    This is a convenience endpoint that combines:
      1. PDF text extraction via pdfplumber
      2. LLM structuring into LabParameterSchema
      3. Automatic submission to the deep research pipeline

    Returns the same response as ``POST /api/v1/lab_parameters`` (txn_id etc.).
    """
    content_type = file.content_type or "application/pdf"
    if "pdf" not in content_type.lower():
        raise HTTPException(status_code=400, detail=f"Expected a PDF file, got {content_type}")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    # Step 1: Extract and structure the PDF into LabParameterSchema JSON
    try:
        lab_json = await extract_lab_json_from_pdf(file_bytes, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Step 2: Override caller-supplied fields
    lab_json["user_id"] = user_id
    lab_json["language"] = language
    lab_json["model"] = model

    # Step 3: Validate via the existing schema
    try:
        lab_data = LabParameterSchema(**lab_json)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Extracted data does not match expected schema: {exc}",
        )

    # Step 4: Delegate to the existing lab_parameters handler
    return await upload_lab_report(lab_data)


@router.post("/pdf_extract_text")
async def pdf_extract_text(
    file: UploadFile = FastAPIFile(..., description="Digitized PDF file"),
):
    """Extract raw text from a PDF using pdfplumber (no LLM call).

    Useful for debugging or when you want to inspect the extracted text
    before converting it to the LabParameterSchema JSON.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    try:
        text = extract_text_from_pdf(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return JSONResponse(
        content={"text": text, "character_count": len(text)},
        status_code=HTTPStatus.OK,
    )


# ---- Background Processing ----

def normalize_report_date(date_str: str) -> str:
    """
    Normalize report date to YYYY-MM-DD format.
    """
    try:
        # Try DD/MM/YYYY format first
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts[0]) == 2:  # DD/MM/YYYY
                day, month, year = parts
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            else:  # MM/DD/YYYY
                month, day, year = parts
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        # Try YYYY-MM-DD format
        if '-' in date_str and len(date_str.split('-')[0]) == 4:
            return date_str  # Already in correct format
        
        # Try MM-DD-YYYY format
        if '-' in date_str:
            parts = date_str.split('-')
            if len(parts[0]) == 2:
                month, day, year = parts
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        # Fallback: use today's date
        print(f"Warning: Could not parse date '{date_str}', using today")
        return datetime.now().strftime("%Y-%m-%d")
        
    except Exception as e:
        print(f"Error normalizing date '{date_str}': {e}")
        return datetime.now().strftime("%Y-%m-%d")


def compute_lab_data_hash(lab_data_dict: dict) -> str:
    """
    Compute a hash of the current values in lab data to detect changes.
    Only hashes currentValue and linkedParameters currentValues (ignores previousValues).
    
    This allows deduplication to detect when actual parameter values have changed,
    even if the same reportId is reused.
    """
    hash_data = {
        "parameterName": lab_data_dict.get("parameterName"),
        "currentValue": lab_data_dict.get("currentValue"),
        "linkedParameters": {}
    }
    
    # Include current values from linked parameters only
    linked = lab_data_dict.get("linkedParameters", {})
    if isinstance(linked, dict):
        for key, param_info in linked.items():
            if isinstance(param_info, dict):
                # Extract only current values for hashing
                current_vals = param_info.get("currentValues", [])
                if current_vals and isinstance(current_vals, list):
                    hash_data["linkedParameters"][key] = {
                        "name": param_info.get("name"),
                        "currentValues": [
                            {"value": cv.get("value"), "date": cv.get("date")}
                            for cv in current_vals
                            if isinstance(cv, dict)
                        ]
                    }
    
    # Create deterministic JSON string and hash it
    json_str = json.dumps(hash_data, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]  # Use first 16 chars for readability


def validate_and_fix_lab_data(lab_data_dict: dict) -> dict:
    """
    Validate and fix the lab data structure to ensure all fields are properly formatted.
    """
    # Ensure previousValues is a list
    if "previousValues" not in lab_data_dict:
        lab_data_dict["previousValues"] = []
    elif not isinstance(lab_data_dict["previousValues"], list):
        print(f"Warning: previousValues is not a list, converting to list")
        lab_data_dict["previousValues"] = []
    
    # Ensure linkedParameters is a dict
    if "linkedParameters" not in lab_data_dict:
        lab_data_dict["linkedParameters"] = {}
    elif not isinstance(lab_data_dict["linkedParameters"], dict):
        print(f"Warning: linkedParameters is not a dict, converting to empty dict")
        lab_data_dict["linkedParameters"] = {}
    
    # Validate each linked parameter
    linked = lab_data_dict.get("linkedParameters", {})
    for param_key, param_info in list(linked.items()):
        if not isinstance(param_info, dict):
            print(f"Warning: linkedParameter {param_key} is not a dict, removing")
            del linked[param_key]
            continue
        
        # Ensure currentValues exists and is a list
        if "currentValues" not in param_info:
            param_info["currentValues"] = []
        elif not isinstance(param_info["currentValues"], list):
            print(f"Warning: currentValues for {param_key} is not a list, converting")
            param_info["currentValues"] = []
        
        # Ensure previousValues exists and is a list
        if "previousValues" not in param_info:
            param_info["previousValues"] = []
        elif not isinstance(param_info["previousValues"], list):
            print(f"Warning: previousValues for {param_key} is not a list, converting")
            param_info["previousValues"] = []
    
    return lab_data_dict


def auto_populate_previous_values(lab_data_dict: dict, previous_summaries: list) -> dict:
    """
    DEPRECATED — no longer called.

    Qdrant now stores only summary_text (no parameter-level data), so auto-populating
    previousValues from Qdrant history is not possible or appropriate.

    All trend analysis and value comparisons must use the previousValues fields supplied
    in the incoming request payload exclusively.
    """
    print("[AUTO-POPULATE] WARNING: auto_populate_previous_values is deprecated and should not be called.")
    return lab_data_dict


# ===== PARALLEL SEARCH FUNCTIONS FOR ALL 4 SOURCES =====

# search_perplexity_source removed — only GPT-4o-mini (OpenAI) is used.


async def search_openai_source(query: str, user_id: str, report_date: str, is_new_user: bool, language_instruction: str, callbacks: list, formatted_data: str = "") -> dict:
    """
    Search using OpenAI deep researcher (uses web search tools).
    
    Returns:
        dict with 'source', 'response', 'error' keys
    """
    try:
        print("[OPENAI] Starting OpenAI deep researcher search...")
        response = await deep_researcher.ainvoke(
            {
                "messages": [("user", query)],
                "user_id": user_id,
                "report_date": report_date,
                "is_followup": not is_new_user,
                "language_instruction": language_instruction,
                "current_summary_context": formatted_data,  # Full formatted data with comparison table
            },
            config={"callbacks": callbacks}
        )
        
        final_report = response.get("final_report") if isinstance(response, dict) else str(response)
        print(f"[OPENAI] Search completed. Response length: {len(final_report)}")
        
        return {
            "source": "openai",
            "response": final_report,
            "error": None
        }
    except Exception as e:
        print(f"[OPENAI] Error: {type(e).__name__}: {str(e)}")
        return {
            "source": "openai",
            "response": None,
            "error": str(e)
        }


async def search_kb_source(user_id: str, query: str, lab_data_dict: dict) -> dict:
    """
    Search knowledge base using Qdrant vector search for medical insights.
    
    Returns:
        dict with 'source', 'response', 'error' keys
    """
    try:
        from .db_chroma import get_embedding, client, COLLECTION_NAME
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        print("[KB] Starting knowledge base search...")
        
        # Create search query from lab data
        param_name = lab_data_dict.get('parameterName', '')
        current_value = lab_data_dict.get('currentValue', '')
        search_text = f"{param_name} {current_value} medical analysis health implications"
        
        # Get similar summaries from all users (general medical knowledge)
        query_embedding = get_embedding(search_text)
        
        search_results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=5,  # Get top 5 similar medical insights
            with_payload=True
        )
        
        if not search_results:
            print("[KB] No results found in knowledge base")
            return {
                "source": "kb",
                "response": "No similar medical insights found in knowledge base.",
                "error": None
            }
        
        # Format KB results — Qdrant stores only summary_text now
        kb_insights = []
        for idx, result in enumerate(search_results[:3], 1):  # Top 3 results
            payload = result.payload
            summary_data = payload.get('summary', {})
            
            if isinstance(summary_data, dict):
                summary_text = (
                    summary_data.get('summary_text', '')
                    or summary_data.get('narrative_summary', '')
                )
                report_date_kb = summary_data.get('report_date', payload.get('date', ''))
                
                if summary_text:
                    kb_insights.append(f"{idx}. [{report_date_kb}] {summary_text[:300]}")
        
        kb_response = "\n\n".join(kb_insights) if kb_insights else "No relevant medical insights found."
        print(f"[KB] Search completed. Found {len(kb_insights)} relevant insights")
        
        return {
            "source": "kb",
            "response": kb_response,
            "error": None
        }
        
    except Exception as e:
        print(f"[KB] Error: {type(e).__name__}: {str(e)}")
        return {
            "source": "kb",
            "response": None,
            "error": str(e)
        }


async def search_tavily_source(lab_data_dict: dict) -> dict:
    """
    Search web using Tavily API for top abnormal/important parameters.
    Limits to 10 parameters max to avoid query length issues.
    
    Returns:
        dict with 'source', 'response', 'error' keys
    """
    try:
        from .tavily_client import tavily_search
        
        print("[TAVILY] Starting Tavily web search...")
        
        # Extract parameters with priority for abnormal ones
        all_params = []
        abnormal_params = []
        normal_params = []
        
        # Get primary parameter (always include)
        primary_name = lab_data_dict.get('parameterName', '')
        primary_value = lab_data_dict.get('currentValue', '')
        
        if primary_name and primary_value:
            all_params.append(f"{primary_name}: {primary_value}")
        
        # Get linked parameters and categorize by abnormality
        linked_params = lab_data_dict.get('linkedParameters') or lab_data_dict.get('linked_parameters', {})
        
        if isinstance(linked_params, dict):
            for param_key, param_info in linked_params.items():
                if isinstance(param_info, dict):
                    lname = param_info.get('name', '')
                    normal_range = param_info.get('normalRange', '')
                    
                    # Extract current value
                    lvalue = None
                    if 'currentValues' in param_info:
                        current_vals = param_info.get('currentValues', [])
                        if isinstance(current_vals, list) and len(current_vals) > 0:
                            first_val = current_vals[0]
                            if isinstance(first_val, dict):
                                lvalue = first_val.get('value')
                    elif 'current' in param_info:
                        current_data = param_info.get('current', {})
                        if isinstance(current_data, dict):
                            lvalue = current_data.get('value')
                    elif 'currentValue' in param_info:
                        lvalue = param_info.get('currentValue')
                    elif 'value' in param_info:
                        lvalue = param_info.get('value')
                    
                    if lname and lvalue:
                        param_str = f"{lname}: {lvalue}"
                        
                        # Try to determine if abnormal based on range
                        is_abnormal = False
                        if normal_range and '-' in normal_range:
                            try:
                                range_parts = normal_range.split('-')
                                min_val = float(range_parts[0].strip())
                                max_val = float(range_parts[1].strip())
                                current_val = float(str(lvalue).replace('%', '').replace(',', '').strip())
                                
                                if current_val < min_val or current_val > max_val:
                                    is_abnormal = True
                                    abnormal_params.append(param_str)
                                else:
                                    normal_params.append(param_str)
                            except (ValueError, IndexError):
                                # If we can't parse, treat as normal priority
                                normal_params.append(param_str)
                        else:
                            # No range info, treat as normal priority
                            normal_params.append(param_str)
        
        # Prioritize: primary + abnormal parameters first, then normal ones
        # Limit to 10 total to avoid Tavily API query length limits
        selected_params = all_params[:1]  # Primary parameter
        selected_params.extend(abnormal_params[:7])  # Up to 7 abnormal
        
        # Fill remaining slots with normal params if we have space
        remaining_slots = 10 - len(selected_params)
        if remaining_slots > 0:
            selected_params.extend(normal_params[:remaining_slots])
        
        if not selected_params:
            print("[TAVILY] No parameters found to search")
            return {
                "source": "tavily",
                "response": "No parameters detected for web search.",
                "error": None
            }
        
        total_params = len(abnormal_params) + len(normal_params) + 1  # +1 for primary
        print(f"[TAVILY] Total parameters: {total_params}, Abnormal: {len(abnormal_params)}, Selected for search: {len(selected_params)}")
        
        # Create search query with selected parameters (max 10)
        search_query = f"Medical significance and clinical implications of {', '.join(selected_params)}"
        
        # Limit query length to avoid 400 errors (Tavily has ~400 char limit for queries)
        if len(search_query) > 400:
            # Truncate to fit
            print(f"[TAVILY] Query too long ({len(search_query)} chars), truncating...")
            # Take fewer parameters
            truncated_params = selected_params[:5]  # Reduce to top 5
            search_query = f"Medical significance and clinical implications of {', '.join(truncated_params)}"
            print(f"[TAVILY] Reduced to top {len(truncated_params)} parameters")
        
        print(f"[TAVILY] Search query ({len(search_query)} chars): {search_query[:200]}...")
        
        search_results = await tavily_search(
            query=search_query,
            max_results=5,
            search_depth="basic",  # Use basic for faster results
            include_answer=True,
            timeout_s=15.0
        )
        
        if not search_results.get("ok"):
            print(f"[TAVILY] Search failed: {search_results.get('error', 'Unknown error')}")
            return {
                "source": "tavily",
                "response": None,
                "error": search_results.get('error', 'Unknown error')
            }
        
        # Format results
        tavily_response = ""
        results = search_results.get("results", [])
        
        if search_results.get("answer"):
            tavily_response += f"Expert Summary: {search_results['answer']}\n\n"
        
        if results:
            snippets = []
            for idx, result in enumerate(results[:5], 1):
                content = result.get("content", "")[:250]
                title = result.get("title", "")
                if content:
                    snippets.append(f"{idx}. {title}: {content}")
            
            if snippets:
                tavily_response += "Web Research Insights:\n" + "\n".join(snippets)
        
        print(f"[TAVILY] Search completed. Found {len(results)} results for {len(abnormal_params)} parameters")
        
        return {
            "source": "tavily",
            "response": tavily_response if tavily_response else "No web results found.",
            "error": None
        }
        
    except Exception as e:
        print(f"[TAVILY] Error: {type(e).__name__}: {str(e)}")
        return {
            "source": "tavily",
            "response": None,
            "error": str(e)
        }


async def supervisor_agent_synthesis(
    perplexity_result: dict,
    openai_result: dict,
    kb_result: dict,
    tavily_result: dict,
    lab_data_dict: dict,
    report_date: str,
    language_instruction: str,
    callbacks: list
) -> dict:
    """
    Supervisor agent that analyzes all 4 source responses and synthesizes the best comprehensive answer.
    
    Args:
        perplexity_result: Result from Perplexity search
        openai_result: Result from OpenAI search
        kb_result: Result from KB search
        tavily_result: Result from Tavily search
        lab_data_dict: Lab data dictionary
        report_date: Report date
        language_instruction: Language instruction for output
        callbacks: Token tracking callbacks
    
    Returns:
        dict with 'final_report', 'sources_used', 'synthesis_method'
    """
    try:
        print("\n" + "="*80)
        print("🧠 SUPERVISOR AGENT: Analyzing all 4 source responses")
        print("="*80)
        
        # Collect successful responses (perplexity removed — OpenAI only)
        sources_data = {
            "openai": openai_result,
            "kb": kb_result,
            "tavily": tavily_result
        }
        
        # Filter out failed sources
        successful_sources = {}
        for source_name, result in sources_data.items():
            if result.get('response') and not result.get('error'):
                successful_sources[source_name] = result['response']
                print(f"✅ {source_name.upper()}: Available ({len(str(result['response']))} chars)")
            else:
                print(f"❌ {source_name.upper()}: Not available ({result.get('error', 'No response')})")
        
        if not successful_sources:
            print("⚠️ No successful sources - returning error")
            return {
                "final_report": "Unable to generate report - all sources failed.",
                "sources_used": [],
                "synthesis_method": "none",
                "error": "All sources failed"
            }
        
        # Format lab data snippet for context
        param_name = lab_data_dict.get('parameterName', '')
        current_value = lab_data_dict.get('currentValue', '')
        lab_snippet = f"Primary Parameter: {param_name} = {current_value}"
        
        # Pre-compute sources block outside f-string to avoid backslash-in-expression
        # error on Python < 3.12 (PEP 701)
        _nl = chr(10)
        _sources_block = _nl.join(
            "📌 SOURCE: " + source.upper() + _nl + response + _nl + "-" * 80
            for source, response in successful_sources.items()
        )

        # Create supervisor synthesis prompt
        supervisor_prompt = f"""You are a Medical Information Synthesis Supervisor Agent. Your task is to analyze multiple AI-generated health analyses and create ONE comprehensive, detailed report.

**IMPORTANT**: This is INFORMATION SYNTHESIS, not medical advice. You are organizing and combining information from multiple sources.

**Patient Lab Data (Report Date: {report_date}):**
{lab_snippet}

**Available Source Responses:**

{_sources_block}

{language_instruction}

**YOUR TASK: Create a Comprehensive Unified Report**

**Synthesis Strategy:**
1. **Parameter Coverage**: Include ALL parameters mentioned by ANY source
2. **Detail Selection**: For each parameter, choose the MOST DETAILED explanation
3. **Accuracy Priority**: If sources conflict, include BOTH perspectives with clear attribution
4. **Completeness**: Combine recommendations from all sources (avoid duplication)
5. **Source Quality**: Prioritize medically-accurate, detailed information

**Selection Criteria:**
- Perplexity: Real-time web search, current medical guidelines
- OpenAI: Deep reasoning, comprehensive analysis
- KB: Historical patient insights, proven patterns
- Tavily: Web research, diverse medical sources

**Output Structure (with emojis):**
### 👋 Personal Greeting & Report Overview
- Warm greeting and overview of all parameters analyzed

### 📊 Understanding Your Results
- **Each Parameter Analysis**: Combine insights from all sources
  - What it means (clearest explanation from any source)
  - Current value interpretation (most detailed source)
  - Reference ranges (include if any source mentions)
  - Clinical significance (combine all perspectives)

### 🔗 How Your Health Factors Connect
- Combine parameter relationships from all sources
- Include all interconnections mentioned

### 💪 Your Personalized Action Plan
#### 🥗 Dietary Recommendations
- Merge all dietary advice (remove duplicates)
- Include specific foods/portions from any source

#### 🏃 Lifestyle Modifications
- Combine exercise/activity recommendations
- Include stress management from any source

### 🔬 Recommended Follow-Up Tests
- Include ALL tests recommended by any source
- Mention recommended timing

### 🌿 Complementary Wellness Tips
- Combine wellness advice from all sources

### 🎯 Key Takeaways & Encouragement
- Synthesize key points from all sources
- Encouraging conclusion

### 📚 Information Sources
- List which sources contributed: {', '.join(successful_sources.keys())}

**Quality Standards:**
- Patient-friendly language
- Specific numbers and values
- Clear action items
- Encouraging tone
- Comprehensive coverage

**Disclaimer**: Add standard medical disclaimer about consulting healthcare providers.

**Generate the complete synthesized report now:**
"""
        
        # Use GPT-4o-mini for synthesis (good balance of quality and cost)
        supervisor_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4, max_tokens=12000, callbacks=callbacks)
        
        print("🤖 Generating supervisor synthesis...")
        supervisor_response = await supervisor_llm.ainvoke(supervisor_prompt)
        final_report = supervisor_response.content
        
        print(f"✅ Supervisor synthesis complete. Output length: {len(final_report)} chars")
        print(f"📊 Sources used: {', '.join(successful_sources.keys())}")
        print("="*80 + "\n")
        
        return {
            "final_report": final_report,
            "sources_used": list(successful_sources.keys()),
            "synthesis_method": "supervisor_agent",
            "sources_count": len(successful_sources),
            "error": None
        }
        
    except Exception as e:
        import traceback
        print(f"❌ Supervisor synthesis failed: {type(e).__name__}: {str(e)}")
        print(traceback.format_exc())
        
        # Fallback: return best available source
        fallback_order = ["openai", "kb", "tavily"]
        for source in fallback_order:
            if source in successful_sources:
                print(f"⚠️ Using fallback source: {source}")
                return {
                    "final_report": successful_sources[source],
                    "sources_used": [source],
                    "synthesis_method": "fallback",
                    "error": str(e)
                }
        
        return {
            "final_report": "Unable to generate report due to synthesis error.",
            "sources_used": [],
            "synthesis_method": "failed",
            "error": str(e)
        }


# ===== END PARALLEL SEARCH FUNCTIONS =====


async def process_universal_report(
    txn_id: str, 
    lab_data_dict: dict,
    report_date: str,
    is_new_user: bool,
    model: str = "openai",
    input_data_hash: str = None
):
    """
    Universal background task that handles both new users and follow-up reports.
    Supports parallel search across all sources: Perplexity, OpenAI, KB, Tavily.
    
    Args:
        input_data_hash: Hash of input values for deduplication tracking
    """
    token_tracker = TokenTracker()
    callbacks = [TokenTrackingCallback(token_tracker)]

    user_id = lab_data_dict.get("user_id")
    
    try:
        print(f"=== Processing universal report for user {user_id} ===")
        print(f"User type: {'NEW' if is_new_user else 'EXISTING'}")
        print(f"Report date: {report_date}")
        
        # Store normalized date
        lab_data_dict['report_date'] = report_date
        
        # Validate and fix data structure
        lab_data_dict = validate_and_fix_lab_data(lab_data_dict)
        
        # Get previous summaries for existing users
        previous_summaries = get_user_summaries(user_id)
        
        # Log retrieved summaries (summary_text only — no parameter-level data)
        if previous_summaries:
            print(f"\n[RETRIEVE] Found {len(previous_summaries)} previous summary texts for user {user_id}")
            for idx, summ in enumerate(previous_summaries):
                summ_data = summ.get('summary', {})
                summary_text_preview = summ_data.get('summary_text', '')[:80] if isinstance(summ_data, dict) else ''
                print(f"[RETRIEVE] Summary {idx+1}: date={summ.get('date')} | text_preview={summary_text_preview!r}")
        else:
            print(f"\n[RETRIEVE] No previous summaries found for user {user_id}")
        
        # Determine whether this request carries comparison data from the payload.
        # NOTE: previousValues must come from the request payload ONLY — Qdrant no longer
        # stores parameter-level data, so auto-population from history is disabled.
        primary_prev_in_payload = lab_data_dict.get('previousValues', [])
        has_payload_previous_values = (
            isinstance(primary_prev_in_payload, list)
            and len(primary_prev_in_payload) > 0
            and any(v.get('value') for v in primary_prev_in_payload if isinstance(v, dict))
        )
        
        # has_auto_populated_data reflects whether the PAYLOAD itself contains usable previous values
        has_auto_populated_data = has_payload_previous_values
        
        if not is_new_user:
            print(f"\n{'='*80}")
            print(f"🔄 FOLLOW-UP REPORT DETECTED")
            print(f"{'='*80}")
            print(f"Found {len(previous_summaries)} previous reports in Qdrant (contextual memory only)")
            print(f"\n📥 PAYLOAD previousValues for primary parameter: {primary_prev_in_payload}")
            
            linked_params_check = lab_data_dict.get('linkedParameters', {})
            comparison_count = 0
            for param_key, param_info in linked_params_check.items():
                if isinstance(param_info, dict):
                    lp_prev = param_info.get('previousValues', [])
                    valid_lp_prev = (
                        isinstance(lp_prev, list)
                        and len(lp_prev) > 0
                        and any(v.get('value') for v in lp_prev if isinstance(v, dict))
                    )
                    if valid_lp_prev:
                        comparison_count += 1
                        curr_vals = param_info.get('currentValues', [])
                        curr = curr_vals[0] if curr_vals else {}
                        latest = lp_prev[-1] if lp_prev else {}
                        print(f"   ✅ {param_info.get('name')}: {latest.get('value')} → {curr.get('value')}")
            
            if has_auto_populated_data:
                print(f"   ✅ Primary parameter has {len(primary_prev_in_payload)} previous values from PAYLOAD")
                print(f"   ✅ COMPARISON WILL BE PERFORMED")
            else:
                print(f"   ⚠️ No previousValues in payload for primary parameter — treating as new-parameter baseline")
            
            print(f"   Linked params with payload previousValues: {comparison_count}")
            print(f"{'='*80}\n")

        
        # Create appropriate context based on user type
        if is_new_user:
            memory_context = "NEW PATIENT - No previous reports in database. This is the first baseline report."
            report_type = "first_report"
            user_type = "new_user"
        else:
            memory_context = format_previous_summaries_for_context(previous_summaries, report_date)
            report_type = "follow_up"
            user_type = "existing_user"
        
        # Use TOON-formatted data
        print(f"\n{'='*80}")
        print(f"[BEFORE FORMAT] Calling format_lab_data_toon with:")
        print(f"{'='*80}")
        print(f"[BEFORE FORMAT]   Primary param: {lab_data_dict.get('parameterName')}")
        
        primary_prev = lab_data_dict.get('previousValues', [])
        print(f"[BEFORE FORMAT]   Primary previousValues: {len(primary_prev)} items")
        if primary_prev:
            print(f"[BEFORE FORMAT]   Primary previousValues DATA: {primary_prev}")
        else:
            print(f"[BEFORE FORMAT]   ⚠️ PRIMARY HAS NO PREVIOUS VALUES!")
        
        linked_check = lab_data_dict.get('linkedParameters', {})
        print(f"[BEFORE FORMAT]   Linked params: {len(linked_check)} total")
        
        # Check ALL linked params previousValues status
        for param_key, param_info in linked_check.items():
            if isinstance(param_info, dict):
                lp_name = param_info.get('name', 'Unknown')
                lp_prev = param_info.get('previousValues', [])
                if lp_prev:
                    print(f"[BEFORE FORMAT]     ✅ {lp_name}: {len(lp_prev)} previousValues = {lp_prev}")
                else:
                    print(f"[BEFORE FORMAT]     ❌ {lp_name}: NO previousValues")
        
        print(f"[BEFORE FORMAT]   Previous summaries: {len(previous_summaries) if not is_new_user else 0}")
        print(f"{'='*80}\n")
        
        formatted_data = format_lab_data_toon(lab_data_dict, previous_summaries if not is_new_user else [])
        
        print(f"\n{'='*80}")
        print(f"[AFTER FORMAT] Formatted data analysis:")
        print(f"{'='*80}")
        print(f"[AFTER FORMAT] Total length: {len(formatted_data)} characters")
        
        # Check if TREND ANALYSIS section is present
        if "📈 TREND ANALYSIS" in formatted_data:
            print(f"[AFTER FORMAT] ✅ TREND ANALYSIS SECTION EXISTS - Follow-up report with history")
            # Count how many parameters have trends
            trend_count = formatted_data.count("- Previous:")
            print(f"[AFTER FORMAT] Found {trend_count} parameters with trend data")
        elif "🆕 FIRST-TIME REPORT" in formatted_data:
            print(f"[AFTER FORMAT] 🆕 FIRST-TIME REPORT MARKER - No previous data")
        else:
            print(f"[AFTER FORMAT] ⚠️ WARNING: No TREND ANALYSIS section and no FIRST-TIME marker!")
        
        print(f"[AFTER FORMAT] Preview (first 800 chars):")
        print(formatted_data[:800])
        print(f"{'='*80}\n")

        
        # === TAVILY SEARCH - RUNS FOR ALL MODELS ===
        print("\n" + "="*80)
        print("🌐 TAVILY WEB SEARCH: Starting for all models")
        print("="*80)
        
        tavily_result = await search_tavily_source(lab_data_dict)
        
        if tavily_result.get('response') and not tavily_result.get('error'):
            tavily_context = tavily_result['response']
            print(f"✅ Tavily search completed successfully ({len(tavily_context)} chars)")
        else:
            tavily_context = ""
            print(f"⚠️ Tavily search failed: {tavily_result.get('error', 'No response')}")
        
        print("="*80 + "\n")
        # === END TAVILY SEARCH ===
        
        # Extract language preference (default to english)
        language = lab_data_dict.get('language', 'english').lower()
        if language not in ['hindi', 'gujarati', 'english', 'marathi', 'malayalam', 'kannada', 'tamil', 'bangla']:
            language = 'english'
        
        # Language instruction mapping
        language_instructions = {
            'hindi': "**भाषा निर्देश**: संपूर्ण विश्लेषण हिंदी में लिखें। सभी चिकित्सा शब्दों को हिंदी में समझाएं।",
            'gujarati': "**ભાષા સૂચના**: સંપૂર્ણ વિશ્લેષણ ગુજરાતીમાં લખો. તમામ તબીબી શબ્દોને ગુજરાતીમાં સમજાવો.",
            'marathi': "**भाषा सूचना**: संपूर्ण विश्लेषण मराठीमध्ये लिहा. सर्व वैद्यकीय शब्दांचे मराठीमध्ये स्पष्टीकरण द्या.",
            'malayalam': "**ഭാഷാ നിർദ്ദേശം**: മുഴുവൻ വിശകലനവും മലയാളത്തിൽ എഴുതുക. എല്ലാ മെഡിക്കൽ പദങ്ങളും മലയാളത്തിൽ വിശദീകരിക്കുക.",
            'kannada': "**ಭಾಷಾ ಸೂಚನೆ**: ಸಂಪೂರ್ಣ ವಿಶ್ಲೇಷಣೆಯನ್ನು ಕನ್ನಡದಲ್ಲಿ ಬರೆಯಿರಿ. ಎಲ್ಲಾ ವೈದ್ಯಕೀಯ ಪದಗಳನ್ನು ಕನ್ನಡದಲ್ಲಿ ವಿವರಿಸಿ.",
            'tamil': "**மொழி அறிவுறுத்தல்**: முழு பகுப்பாய்வையும் தமிழில் எழுதவும். அனைத்து மருத்துவ சொற்களையும் தமிழில் விளக்கவும்.",
            'bangla': "**ভাষা নির্দেশনা**: সম্পূর্ণ বিশ্লেষণ বাংলায় লিখুন। সমস্ত চিকিৎসা শব্দ বাংলায় ব্যাখ্যা করুন।",
            'english': "**LANGUAGE INSTRUCTION**: Write the entire analysis in English."
        }
        
        language_instruction = language_instructions.get(language, language_instructions['english'])
        
        # Create appropriate query based on user type and available data
        if is_new_user:
            # Add Tavily context to the query if available
            tavily_addition = f"\n\n### 🌐 Web Research Context (Tavily):\n{tavily_context}" if tavily_context else ""
            
            query = f"""{memory_context}

**FIRST-TIME BASELINE REPORT - NEW PATIENT**

{language_instruction}

Report Date: {report_date}
This is the patient's FIRST report. No historical data exists in our database.

{formatted_data}{tavily_addition}

Provide comprehensive baseline analysis:

1. BASELINE ASSESSMENT:
   - Interpret current values using Indian reference ranges
   - Identify any abnormal values and their clinical significance
   - Establish health baseline for future comparisons

2. HEALTH STATUS:
   - Overall health assessment based on current parameters
   - Potential risk factors and areas of concern
   - Positive health indicators

3. RECOMMENDATIONS & GOALS:
   - Specific dietary guidance (Indian context)
   - Lifestyle modifications and exercise recommendations
   - Monitoring frequency for future tests
   - When to consult a healthcare provider

Be encouraging and set positive expectations.

**CRITICAL**: Clearly state this is the patient's first report and these values will serve as their baseline."""
        
        else:
            # Existing user - check if we have comparison data
            auto_populated_previous = lab_data_dict.get('previousValues', [])
            
            if has_auto_populated_data:
                # We have actual previous values for comparison
                prev_sample = auto_populated_previous[0] if auto_populated_previous else {}
                # Build explicit comparison statement
                primary_param = lab_data_dict.get('parameterName', 'Parameter')
                current_val = lab_data_dict.get('currentValue', 'N/A')
                prev_val = prev_sample.get('value', 'N/A')
                prev_date = prev_sample.get('date', 'N/A')
                
                comparison_context = f"""**🔄 FOLLOW-UP REPORT WITH HISTORICAL COMPARISON - COMPARISON IS MANDATORY**

✅ Previous reports found: {len(previous_summaries)}
✅ Auto-populated previous values: {len(auto_populated_previous)}

🎯 PRIMARY COMPARISON REQUIRED:
   Parameter: {primary_param}
   Previous: {prev_val} (on {prev_date})
   Current:  {current_val} (on {report_date})
   
⚠️ YOU MUST:
1. Calculate and state the exact change: "{current_val} vs {prev_val}" 
2. Calculate percentage change if numerical
3. State if this is improvement, decline, or stable
4. Explain clinical significance of this change
5. Compare ALL parameters that have previous values (check for trend arrows ↑ ↓ →)

⚠️ CRITICAL: This is a FOLLOW-UP report. The patient wants to know if their values improved or worsened.
Do NOT treat this as a first-time report. ALWAYS reference and compare with previous values shown."""
            else:
                # Existing user but no matching parameter history
                comparison_context = f"""**FOLLOW-UP VISIT - NEW PARAMETER**

User has {len(previous_summaries)} previous report(s) in database.
However, this is the first time testing this specific parameter.

Treat as baseline for this parameter while acknowledging user's existing history."""
            
            # Add Tavily context to the query if available
            tavily_addition = f"\n\n### 🌐 Web Research Context (Tavily):\n{tavily_context}" if tavily_context else ""
            
            query = f"""{memory_context}

{comparison_context}

{language_instruction}

Report Date: {report_date}
Previous Reports Count: {len(previous_summaries)}

{formatted_data}{tavily_addition}

Provide follow-up analysis:

1. CURRENT STATUS:
   - Interpret current values using Indian reference ranges
   - {"Compare with previous values - show specific improvements/declines" if has_auto_populated_data else "Establish baseline for this new parameter"}
   - Note any concerning trends or positive developments

2. TREND ANALYSIS:
   - {"Specific numerical comparisons with dates and values" if has_auto_populated_data else "Acknowledge this is first measurement for this parameter"}
   - Interconnected parameter relationships
   - Progress since last assessment

3. RECOMMENDATIONS:
   - Adjusted dietary guidance based on trends
   - Modified exercise/lifestyle recommendations
   - Next monitoring schedule
   - When to seek medical attention

Acknowledge patient efforts if values improved.

**CRITICAL**: {"Provide specific before/after comparisons with numbers" if has_auto_populated_data else "Note this parameter is new to the patient's history"}"""
        
        # ===== NEW: PARALLEL SEARCH ACROSS ALL 4 SOURCES WITH SUPERVISOR =====
        
        # Check if user wants old legacy mode (single source) or new multi-source mode
        # New mode: "all" triggers parallel search with supervisor
        # Legacy modes: "openai", "perplexity", "perplexity+openai" still work as before
        
        if model == "all":
            print("\n" + "="*80)
            print("🚀 MULTI-SOURCE MODE: Searching all 4 sources in parallel")
            print("📌 Supervisor: OpenAI (GPT-4o-mini)")
            print("="*80)
            
            # Launch 3 searches in parallel (OpenAI + KB + Tavily)
            print("📡 Launching parallel searches...")
            search_tasks = [
                search_openai_source(query, user_id, report_date, is_new_user, language_instruction, callbacks, formatted_data),
                search_kb_source(user_id, query, lab_data_dict),
                search_tavily_source(lab_data_dict)
            ]
            
            # Wait for all searches to complete
            search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            # Unpack results
            perplexity_result = {"source": "perplexity", "response": None, "error": "disabled"}
            openai_result = search_results[0] if not isinstance(search_results[0], Exception) else {"source": "openai", "response": None, "error": str(search_results[0])}
            kb_result = search_results[1] if not isinstance(search_results[1], Exception) else {"source": "kb", "response": None, "error": str(search_results[1])}
            tavily_result = search_results[2] if not isinstance(search_results[2], Exception) else {"source": "tavily", "response": None, "error": str(search_results[2])}
            
            print("✅ All parallel searches completed")
            
            # Pass all results to supervisor for synthesis (OpenAI is supervisor)
            synthesis_result = await supervisor_agent_synthesis(
                perplexity_result=perplexity_result,
                openai_result=openai_result,
                kb_result=kb_result,
                tavily_result=tavily_result,
                lab_data_dict=lab_data_dict,
                report_date=report_date,
                language_instruction=language_instruction,
                callbacks=callbacks
            )
            
            main_insight = synthesis_result.get("final_report")
            sources_used = synthesis_result.get("sources_used", [])
            models_used = "all-sources (openai+kb+tavily, supervisor: openai)"
            
            print(f"✅ Multi-source analysis complete using: {', '.join(sources_used)}")
            print(f"📊 Final supervisor: OpenAI (GPT-4o-mini)")
            
        else:
            # ===== OPENAI MODE =====
            from datetime import datetime as dt
            report_type_explicit = "FOLLOW-UP REPORT" if not is_new_user else "FIRST-TIME REPORT"
            
            structured_query = final_report_generation_prompt.format(
                previous_report_summary=memory_context,
                current_summary_context=formatted_data,
                research_brief=query,  # Use the query we built as research context
                messages="",  # No conversation history in this endpoint
                findings=formatted_data,  # Use lab data as findings
                language_instruction=language_instruction,
                report_date=report_date,
                report_type=report_type_explicit,  # ← ADD THIS
                date=dt.now().strftime("%Y-%m-%d")
            )
            
            # Always use OpenAI (GPT-4o-mini) + Tavily
            print("🤖 Using OpenAI (GPT-4o-mini) with Tavily web research")
            clean_query = f"""
{language_instruction}

Report Date: {report_date}
Report Type: {report_type_explicit}

{formatted_data}

**Additional Web Research Context:**
{tavily_context if tavily_context else 'No web research available'}

Provide comprehensive clinical analysis following the report structure guidelines.
"""
            response = await deep_researcher.ainvoke(
                {
                    "messages": [("user", clean_query)],
                    "user_id": user_id,
                    "report_date": report_date,
                    "is_followup": not is_new_user,
                    "language_instruction": language_instruction,
                    "previous_report_summary": memory_context,
                    "current_summary_context": formatted_data,
                },
                config={"callbacks": callbacks}
            )
            main_insight = response.get("final_report") if isinstance(response, dict) else str(response)
            models_used = "openai+tavily"
        
        # Create structured summary
        structured_summary = await create_structured_summary(lab_data_dict, main_insight, report_date)
        
        # Debug: Log what's being saved
        print(f"\n[SAVE SUMMARY] Structured summary keys: {list(structured_summary.keys())}")
        if 'linked_parameters' in structured_summary:
            linked_in_summary = structured_summary['linked_parameters']
            print(f"[SAVE SUMMARY] Linked parameters count: {len(linked_in_summary)}")
            for lp in linked_in_summary[:5]:  # Show first 5
                print(f"[SAVE SUMMARY]   - {lp.get('name')}: {lp.get('value')} {lp.get('unit')}")
        else:
            print(f"[SAVE SUMMARY] WARNING: No 'linked_parameters' key in structured summary!")
        
        # Generate appropriate narrative summary
        summarizer = ChatOpenAI(
            model="gpt-5-nano",
            callbacks=callbacks
        )

        
        if is_new_user:
            # First-time report summary
            summary_prompt = ChatPromptTemplate.from_template(
                """Create a 2-3 sentence summary for a FIRST-TIME patient report.

{language_instruction}

Primary Parameter: {param_name} = {current_value}
Report Date: {report_date}
Key Insights: {insight}

Focus on: 1) Baseline health status, 2) Main finding, 3) Primary recommendation.
Clearly state this is their first report and baseline measurement."""
            )
            summary_input = {
                "language_instruction": language_instruction,
                "param_name": structured_summary['primary_parameter']['name'],
                "current_value": f"{structured_summary['primary_parameter']['current_value']} {structured_summary['primary_parameter']['unit']}",
                "report_date": report_date,
                "insight": main_insight[:400]
            }
        else:
            # Follow-up report summary
            if has_auto_populated_data and previous_summaries:
                last_summary = previous_summaries[0]
                last_summary_data = last_summary.get('summary', {})
                
                # Qdrant stores only summary_text now — no primary_parameter data.
                # Use previousValues from the payload for the actual previous figure.
                prev_payload_vals = lab_data_dict.get('previousValues', [])
                if prev_payload_vals and isinstance(prev_payload_vals[0], dict):
                    prev_value = str(prev_payload_vals[0].get('value', 'N/A'))
                else:
                    prev_value = "N/A"
                
                current_value = f"{structured_summary['primary_parameter']['current_value']} {structured_summary['primary_parameter']['unit']}"
                
                summary_prompt = ChatPromptTemplate.from_template(
                    """Create a 2-3 sentence follow-up summary comparing current and previous values.

{language_instruction}

Previous {param_name}: {prev_value} (from {prev_date})
Current {param_name}: {current_value} (from {current_date})
Key Trend: {insight}

Highlight: 1) Parameter change direction, 2) Clinical significance, 3) Brief next steps.
Mention this is a follow-up comparison."""
                )
                summary_input = {
                    "language_instruction": language_instruction,
                    "param_name": structured_summary['primary_parameter']['name'],
                    "prev_value": prev_value,
                    "prev_date": last_summary.get('date', 'previous'),
                    "current_value": current_value,
                    "current_date": report_date,
                    "insight": main_insight[:400]
                }
            else:
                # Follow-up but no direct comparison data
                summary_prompt = ChatPromptTemplate.from_template(
                    """Create a 2-3 sentence summary for follow-up visit with new parameter.

{language_instruction}

Patient has {prev_count} previous reports, but this is first time testing {param_name}.
Current {param_name}: {current_value}
Report Date: {report_date}
Key Findings: {insight}

Mention: 1) New parameter baseline, 2) Overall health context, 3) Monitoring plan."""
                )
                summary_input = {
                    "language_instruction": language_instruction,
                    "prev_count": len(previous_summaries),
                    "param_name": structured_summary['primary_parameter']['name'],
                    "current_value": f"{structured_summary['primary_parameter']['current_value']} {structured_summary['primary_parameter']['unit']}",
                    "report_date": report_date,
                    "insight": main_insight[:400]
                }
        
        summary_response = await (summary_prompt | summarizer).ainvoke(summary_input)
        narrative_summary = summary_response.content.strip()
        
        structured_summary['narrative_summary'] = narrative_summary
        structured_summary['is_followup'] = not is_new_user
        
            # usage_summary = getattr(summary_response, "usage", None)
            # if usage_summary:
            #     usage_summary = {
            #         "prompt_tokens": usage_summary.prompt_tokens,
            #         "completion_tokens": usage_summary.completion_tokens,
            #         "total_tokens": usage_summary.total_tokens,
            #     }
            # else:
            #     est_tokens = estimate_tokens(narrative_summary)
            #     usage_summary = {
            #         "prompt_tokens": int(est_tokens * 0.5),
            #         "completion_tokens": int(est_tokens * 0.5),
            #         "total_tokens": est_tokens,
            #     }
        
        total_usage = {
            "prompt_tokens": token_tracker.input_tokens,
            "completion_tokens": token_tracker.output_tokens,
            "total_tokens": token_tracker.total_tokens,
        }
        
        # GPT-4o-mini pricing
        input_cost_usd = (total_usage["prompt_tokens"] / 1_000_000) * 0.15
        output_cost_usd = (total_usage["completion_tokens"] / 1_000_000) * 0.60
        text_analysis_cost_usd = input_cost_usd + output_cost_usd
        
        text_analysis_cost_inr = text_analysis_cost_usd * 88
        
        # Save ONLY the narrative summary_text to Qdrant for contextual memory.
        # Full structured_summary (parameters, values, etc.) is NOT stored in Qdrant.
        summary_text_to_save = narrative_summary  # plain text, 2-3 sentences
        save_summary(user_id, summary_text_to_save, date=report_date)
        print(f"✅ Saved summary_text to Qdrant for user {user_id} on {report_date}")
        
        # Store language for later voice generation (when /generate_voice is called)
        language = lab_data_dict.get('language', 'english')
        print(f"💾 Stored language preference: {language.upper()} (voice will be generated on-demand)")
        
        # Calculate total costs (text analysis only - no voice generation)
        total_cost_usd = text_analysis_cost_usd
        total_cost_inr = total_cost_usd * 88
        
        # Prepare final result
        # determine is_first_time from transaction cache (set at creation)
        is_first_time_flag = transaction_cache.get(txn_id, {}).get("is_first_time", False)

        result = ensure_json_safe({
            "status": "success",
            "user_id": user_id,
            "report_date": report_date,
            "reportId": lab_data_dict.get('report_id'),
            "report_type": report_type,
            "user_type": user_type,
            "is_new_user": is_new_user,
            "has_comparison_data": has_auto_populated_data,
            "previous_reports_count": len(previous_summaries),
            "auto_populated_previous_values": len(lab_data_dict.get('previousValues', [])),
            "model_used": models_used,  # Will show combined models if multi-model mode
            "final_result": main_insight,
            "summary": narrative_summary,
            "structured_summary": structured_summary,
            "voice_explanation": None,  # Voice not generated yet - call /generate_voice endpoint
            "language": language,
            "usage": total_usage,
            "cost_estimate_usd": round(total_cost_usd, 6),
            "cost_estimate_inr": round(total_cost_inr, 4),
            "cost_breakdown": {
                "text_analysis_usd": round(text_analysis_cost_usd, 6),
                "text_analysis_inr": round(text_analysis_cost_inr, 4),
                "voice_generation_usd": 0.0,  # Voice not generated in this request
                "voice_generation_inr": 0.0,
                "total_usd": round(total_cost_usd, 6),
                "total_inr": round(total_cost_inr, 4)
            },
            "input_data_hash": input_data_hash  # Store hash for future deduplication
        })
        
        # Update transaction
        txn_data = transaction_cache.get(txn_id, {})
        txn_data.update({
            "status": "COMPLETED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": result
        })
        
        transaction_cache[txn_id] = txn_data
        save_transaction_to_db(txn_data)
        
        print(f"✅ Universal report completed for txn_id={txn_id}")
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Universal report failed for txn_id={txn_id}")
        print(f"Error: {e}")
        print(f"Full traceback:\n{error_details}")
        
        txn_data = transaction_cache.get(txn_id, {})
        txn_data.update({
            "status": "FAILED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": {
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": error_details[:1000]
            }
        })
        
        transaction_cache[txn_id] = txn_data
        save_transaction_to_db(txn_data)
        print(
            f"[TOKENS][TXN {txn_id}] "
            f"Input={token_tracker.input_tokens}, "
            f"Output={token_tracker.output_tokens}, "
            f"Total={token_tracker.total_tokens}"
        )


@router.delete("/delete_analysis/{txn_id}")
async def delete_report_by_transaction(txn_id: str):
    """
    Delete a specific report using its transaction ID.
    
    This endpoint removes:
    - The specific transaction record from SQLite
    - The corresponding summary from Qdrant (matched by user_id and report_date)
    - Cached transaction if present
    
    Use cases:
    - Delete any specific report (1st, 2nd, 3rd, or latest)
    - Remove incorrect/duplicate reports
    - Clean up test data
    
    Example:
    - User has 4 reports with txn_ids: [txn1, txn2, txn3, txn4]
    - To delete 2nd report: DELETE /report/txn2
    - Only txn2 report is deleted, others remain intact
    
    Args:
        txn_id: The transaction ID of the report to delete
        
    Returns:
        Details of the deleted report including user_id and report_date
    """
    if not txn_id or not txn_id.strip():
        raise HTTPException(status_code=400, detail="txn_id cannot be empty")
    
    try:
        deletion_info = {
            "txn_id": txn_id,
            "deleted_transaction": None,
            "deleted_summary": None,
            "cache_removed": False
        }
        
        # 1. Find and delete the specific transaction from SQLite
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get the transaction details first
            cursor.execute("""
                SELECT txn_id, user_id, lab_parameter, started_at, completed_at, status, result_json
                FROM transactions 
                WHERE txn_id = ?
            """, (txn_id,))
            
            txn_row = cursor.fetchone()
            
            if not txn_row:
                raise HTTPException(
                    status_code=404, 
                    detail=f"Transaction {txn_id} not found"
                )
            
            user_id = txn_row["user_id"]
            result_json = txn_row["result_json"]
            
            # Extract report_date from result_json
            report_date = None
            if result_json:
                try:
                    result_data = json.loads(result_json)
                    report_date = result_data.get("report_date")
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse result_json for txn_id {txn_id}")
            
            deletion_info["deleted_transaction"] = {
                "txn_id": txn_id,
                "user_id": user_id,
                "lab_parameter": txn_row["lab_parameter"],
                "report_date": report_date,
                "started_at": txn_row["started_at"],
                "completed_at": txn_row["completed_at"],
                "status": txn_row["status"]
            }
            
            # Delete this specific transaction
            cursor.execute("DELETE FROM transactions WHERE txn_id = ?", (txn_id,))
        
        print(f"✅ Deleted transaction {txn_id} for user {user_id}")
        
        # 2. Delete the corresponding summary from Qdrant (if report_date is available)
        if report_date and user_id:
            from .db_chroma import delete_summary_by_date
            
            deleted_summary = delete_summary_by_date(user_id, report_date)
            
            if deleted_summary:
                deletion_info["deleted_summary"] = {
                    "user_id": user_id,
                    "report_date": report_date,
                    "parameter": deleted_summary.get("summary", {}).get("primary_parameter", {}).get("name"),
                    "point_id": deleted_summary.get("id")
                }
                print(f"✅ Deleted summary for user {user_id} dated {report_date}")
            else:
                print(f"⚠️ No matching summary found in Qdrant for user {user_id}, date {report_date}")
                deletion_info["deleted_summary"] = {
                    "note": "No matching summary found in Qdrant"
                }
        else:
            print(f"⚠️ Could not extract report_date from transaction, skipping Qdrant deletion")
            deletion_info["deleted_summary"] = {
                "note": "Report date not found, could not delete from Qdrant"
            }
        
        # 3. Clear from in-memory cache
        if txn_id in transaction_cache:
            del transaction_cache[txn_id]
            deletion_info["cache_removed"] = True
            print(f"✅ Removed cache entry for txn_id {txn_id}")
        
        # 4. Get remaining reports count for this user
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (user_id,))
            remaining_count = cursor.fetchone()[0]
        
        return JSONResponse(
            content={
                "message": f"Successfully deleted report with transaction ID {txn_id}",
                "deletion_info": deletion_info,
                "remaining_reports": remaining_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "note": f"User {user_id} now has {remaining_count} report(s) remaining"
            },
            status_code=HTTPStatus.OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Error deleting report for txn_id {txn_id}: {e}")
        print(error_details)
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete report: {str(e)}"
        )


# ---- Voice Generation Endpoints ----

class GenerateVoiceRequest(BaseModel):
    """Request model for generating or regenerating voice"""
    user_id: str = Field(..., description="User ID who owns the report")
    report_id: Optional[str] = Field(None, description="Report ID to generate voice for")
    txn_id: Optional[str] = Field(None, description="Transaction ID to generate voice for when report_id is unavailable")
    language: Optional[str] = Field(None, description="Language for voice generation (english, hindi, gujarati, marathi, malayalam, kannada, tamil, bangla). If not provided, uses language from deep research.")


class ReportCheckRequest(BaseModel):
    """Request model for checking if report exists"""
    report_id: str = Field(..., description="Report ID to check")
    user_id: str = Field(..., description="User ID who owns the report")


@router.post("/report_check_for_voice")
async def report_check_for_voice(request: ReportCheckRequest):
    """
    Check if a report exists for the given report_id and user_id.
    
    This endpoint queries the deep_research_transactions.db directly using both
    report_id and user_id to verify:
    1. A transaction exists with the given report_id AND user_id
    2. The transaction has completed successfully
    
    Args:
        request: Contains report_id and user_id
        
    Returns:
        JSON with isReportFound field (true/false)
    """
    try:
        # Query database directly with both report_id AND user_id
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, txn_id, report_id, user_id, completed_at
                FROM transactions 
                WHERE report_id = ? AND user_id = ?
                LIMIT 1
            """, (request.report_id, request.user_id))
            
            row = cursor.fetchone()
            
            # Check if transaction exists and is completed
            if row and row["status"] == "COMPLETED":
                print(f"✅ Report found: report_id={request.report_id}, user_id={request.user_id}, txn_id={row['txn_id']}")
                return JSONResponse(
                    content={"isReportFound": "true"},
                    status_code=HTTPStatus.OK
                )
            elif row:
                print(f"⚠️ Report found but status is '{row['status']}': report_id={request.report_id}, user_id={request.user_id}")
                return JSONResponse(
                    content={"isReportFound": "false"},
                    status_code=HTTPStatus.OK
                )
            else:
                return JSONResponse(
                    content={"isReportFound": "false"},
                    status_code=HTTPStatus.OK
                )
        
    except Exception as e:
        print(f"❌ Error checking report: {e}")
        return JSONResponse(
            content={"isReportFound": "false"},
            status_code=HTTPStatus.OK
        )


@router.post("/generate_voice")
async def generate_voice(request: GenerateVoiceRequest):

    try:
        if not request.report_id and not request.txn_id:
            raise HTTPException(status_code=400, detail="Either report_id or txn_id is required")

        transaction = None
        lookup_key = None

        if request.report_id:
            transaction = get_transaction_by_report_id(request.report_id, request.user_id)
            lookup_key = request.report_id

        if not transaction and request.txn_id:
            transaction = get_transaction_from_db(request.txn_id)
            lookup_key = request.txn_id
        
        if not transaction:
            raise HTTPException(
                status_code=404,
                detail=f"Report not found for key '{lookup_key}' and user {request.user_id}"
            )
        
        # Verify user_id matches (redundant now but kept for safety)
        if transaction["user_id"] != request.user_id:
            raise HTTPException(
                status_code=403,
                detail=f"Requested report does not belong to user {request.user_id}"
            )
        
        # Check if transaction has completed successfully
        if transaction["status"] != "COMPLETED":
            raise HTTPException(
                status_code=400,
                detail=f"Report has status '{transaction['status']}'. Only completed reports can generate voice."
            )
        
        result = transaction.get("result")
        if not result:
            raise HTTPException(
                status_code=400,
                detail=f"Report {request.report_id} has no result data"
            )
        
        # Determine language: use provided language if available, otherwise use stored language
        is_regeneration = request.language is not None
        
        if is_regeneration:
            # Regeneration mode: validate provided language
            language = request.language.lower().strip()
            if language not in ['english', 'hindi', 'gujarati', 'marathi', 'malayalam', 'kannada', 'tamil', 'bangla']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid language '{request.language}'. Supported: english, hindi, gujarati, marathi, malayalam, kannada, tamil, bangla"
                )
            action = "Regenerating"
            action_past = "regenerated"
        else:
            # First-time generation: use stored language from deep research
            language = result.get("language", "english").lower().strip()
            
            # Validate language
            if language not in ['english', 'hindi', 'gujarati', 'marathi', 'malayalam', 'kannada', 'tamil', 'bangla']:
                print(f"⚠️ Invalid stored language '{language}', defaulting to english")
                language = 'english'
            
            action = "Generating"
            action_past = "generated"
        
        # Extract necessary data
        structured_summary = result.get("structured_summary")
        final_result = result.get("final_result")
        report_date = result.get("report_date")
        user_type = result.get("user_type", "returning_user")
        is_new_user = user_type == "first_time_user"
        
        if not structured_summary:
            raise HTTPException(
                status_code=400,
                detail=f"Report {request.report_id} is missing structured_summary"
            )
        
        if not final_result:
            raise HTTPException(
                status_code=400,
                detail=f"Report {request.report_id} is missing final_result (analysis text)"
            )
        
        # Generate voice with determined language
        report_identifier = transaction.get("report_id") or request.report_id or request.txn_id
        print(f"🎙️ {action} voice for report {report_identifier} in {language.upper()}...")
        
        voice_explanation = await generate_health_voice_insight(
            full_analysis=final_result,
            structured_summary=structured_summary,
            user_id=request.user_id,
            report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
            txn_id=transaction["txn_id"],
            is_new_user=is_new_user,
            language=language
        )
        
        # Update the transaction result with voice data
        result["voice_explanation"] = voice_explanation
        if is_regeneration:
            result["voice_language"] = language
            result["voice_regenerated_at"] = datetime.now(timezone.utc).isoformat()
        else:
            result["voice_generated_at"] = datetime.now(timezone.utc).isoformat()
        
        # Save updated transaction
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transactions 
                SET result_json = ?, updated_at = ?
                WHERE txn_id = ?
            """, (
                json.dumps(result),
                datetime.now(timezone.utc).isoformat(),
                transaction["txn_id"]
            ))
        
        # Update cache if present
        if transaction["txn_id"] in transaction_cache:
            transaction_cache[transaction["txn_id"]]["result"]["voice_explanation"] = voice_explanation
            if is_regeneration:
                transaction_cache[transaction["txn_id"]]["result"]["voice_language"] = language
        
        # Calculate voice generation costs
        voice_script_tokens = 600  # Estimated max tokens for voice script generation
        voice_script_cost_usd = (voice_script_tokens / 1_000_000) * 0.60  # GPT-4o-mini output tokens pricing
        
        # Sarvam AI TTS cost: ₹15 per 10,000 characters
        voice_script_text = voice_explanation.get("voice_agent_script", "") if isinstance(voice_explanation, dict) else ""
        voice_char_count = len(voice_script_text)
        sarvam_tts_cost_inr = (voice_char_count / 10000) * 15  # ₹15 per 10k characters
        sarvam_tts_cost_usd = sarvam_tts_cost_inr / 88  # Convert INR to USD
        
        voice_total_cost_usd = voice_script_cost_usd + sarvam_tts_cost_usd
        voice_total_cost_inr = voice_total_cost_usd * 88
        
        print(f"✅ Voice {action_past} successfully for report {report_identifier} in {language.upper()}")
        _voice_action = "regeneration" if is_regeneration else "generation"
        print(f"💰 Voice {_voice_action} cost: ${voice_total_cost_usd:.6f} (₹{voice_total_cost_inr:.4f})")
        
        return JSONResponse(
            content={
                "status": "success",
                "message": f"Voice {action_past} in {language.upper()}",
                "mode": "regeneration" if is_regeneration else "generation",
                "user_id": request.user_id,
                "report_id": transaction.get("report_id") or request.report_id,
                "txn_id": transaction["txn_id"],
                "language": language,
                "voice_explanation": voice_explanation,
                "generated_at" if not is_regeneration else "regenerated_at": datetime.now(timezone.utc).isoformat(),
                "cost_estimate": {
                    "voice_generation_usd": round(voice_total_cost_usd, 6),
                    "voice_generation_inr": round(voice_total_cost_inr, 4),
                    "breakdown": {
                        "gpt_script_generation_usd": round(voice_script_cost_usd, 6),
                        "sarvam_tts_inr": round(sarvam_tts_cost_inr, 4),
                        "character_count": voice_char_count
                    }
                }
            },
            status_code=HTTPStatus.OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Error generating voice for request (report_id={request.report_id}, txn_id={request.txn_id}): {e}")
        print(error_details)
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate voice: {str(e)}"
        )