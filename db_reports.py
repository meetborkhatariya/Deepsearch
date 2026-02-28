"""SQLite database for storing lab report analysis transactions"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, Optional, List
import os
from contextlib import contextmanager

DB_PATH = "lab_reports.db"


@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Allow dict-like access to rows
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize the database with required tables"""
    with get_db() as conn:
        c = conn.cursor()
        
        # Transaction/Report table
        c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            report_id TEXT,
            parameter_name TEXT,
            status TEXT NOT NULL,
            started_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP,
            report_date TEXT,
            user_type TEXT,
            is_first_time INTEGER DEFAULT 0,
            previous_reports_count INTEGER DEFAULT 0,
            
            -- Store result as JSON
            result TEXT,
            
            -- Error tracking
            error TEXT,
            error_type TEXT,
            
            -- Metadata
            language TEXT DEFAULT 'english',
            model TEXT DEFAULT 'openai',
            token_usage TEXT,
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Index for efficient queries
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_id 
        ON transactions(user_id)
        """)
        
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_date 
        ON transactions(report_date)
        """)
        
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_status 
        ON transactions(status)
        """)
        
        # User preferences table
        c.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT PRIMARY KEY,
            default_language TEXT DEFAULT 'english',
            notification_enabled INTEGER DEFAULT 1,
            last_accessed TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        conn.commit()
        print(f"✓ SQLite database initialized at {DB_PATH}")


def save_transaction(txn_data: Dict) -> None:
    """
    Save or update a transaction in the database
    
    Args:
        txn_data: Transaction data dictionary
    """
    with get_db() as conn:
        c = conn.cursor()
        
        # Extract fields
        txn_id = txn_data.get("txn_id")
        if not txn_id:
            raise ValueError("txn_id is required")
        
        # Serialize complex fields to JSON
        result_json = json.dumps(txn_data.get("result")) if txn_data.get("result") else None
        token_usage_json = json.dumps(txn_data.get("token_usage")) if txn_data.get("token_usage") else None
        
        # Check if exists
        c.execute("SELECT txn_id FROM transactions WHERE txn_id = ?", (txn_id,))
        exists = c.fetchone() is not None
        
        if exists:
            # Update existing
            c.execute("""
            UPDATE transactions SET
                status = ?,
                completed_at = ?,
                result = ?,
                error = ?,
                error_type = ?,
                token_usage = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE txn_id = ?
            """, (
                txn_data.get("status"),
                txn_data.get("completed_at"),
                result_json,
                txn_data.get("error"),
                txn_data.get("error_type"),
                token_usage_json,
                txn_id
            ))
        else:
            # Insert new
            c.execute("""
            INSERT INTO transactions (
                txn_id, user_id, report_id, parameter_name, status,
                started_at, completed_at, report_date, user_type,
                is_first_time, previous_reports_count, result, error,
                error_type, language, model, token_usage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                txn_id,
                txn_data.get("user_id"),
                txn_data.get("reportId") or txn_data.get("report_id"),
                txn_data.get("parameter_name"),
                txn_data.get("status"),
                txn_data.get("started_at"),
                txn_data.get("completed_at"),
                txn_data.get("report_date"),
                txn_data.get("user_type"),
                1 if txn_data.get("isFirstTime") or txn_data.get("is_first_time") else 0,
                txn_data.get("previous_reports_count", 0),
                result_json,
                txn_data.get("error"),
                txn_data.get("error_type"),
                txn_data.get("language", "english"),
                txn_data.get("model", "openai"),
                token_usage_json
            ))
        
        conn.commit()


def get_transaction(txn_id: str) -> Optional[Dict]:
    """
    Retrieve a transaction by ID
    
    Args:
        txn_id: Transaction ID
        
    Returns:
        Transaction dict or None if not found
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,))
        row = c.fetchone()
        
        if not row:
            return None
        
        # Convert to dict
        txn_data = dict(row)
        
        # Deserialize JSON fields
        if txn_data.get("result"):
            txn_data["result"] = json.loads(txn_data["result"])
        if txn_data.get("token_usage"):
            txn_data["token_usage"] = json.loads(txn_data["token_usage"])
        
        # Convert boolean
        txn_data["isFirstTime"] = bool(txn_data.get("is_first_time"))
        
        return txn_data


def get_user_transactions(
    user_id: str, 
    limit: int = 10, 
    status: Optional[str] = None
) -> List[Dict]:
    """
    Get all transactions for a user
    
    Args:
        user_id: User ID
        limit: Maximum number of results
        status: Filter by status (PENDING, COMPLETED, FAILED)
        
    Returns:
        List of transaction dicts
    """
    with get_db() as conn:
        c = conn.cursor()
        
        if status:
            c.execute("""
            SELECT * FROM transactions 
            WHERE user_id = ? AND status = ?
            ORDER BY started_at DESC
            LIMIT ?
            """, (user_id, status, limit))
        else:
            c.execute("""
            SELECT * FROM transactions 
            WHERE user_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """, (user_id, limit))
        
        rows = c.fetchall()
        
        transactions = []
        for row in rows:
            txn_data = dict(row)
            
            # Deserialize JSON fields
            if txn_data.get("result"):
                txn_data["result"] = json.loads(txn_data["result"])
            if txn_data.get("token_usage"):
                txn_data["token_usage"] = json.loads(txn_data["token_usage"])
            
            txn_data["isFirstTime"] = bool(txn_data.get("is_first_time"))
            
            transactions.append(txn_data)
        
        return transactions


def get_all_pending_transactions(limit: int = 50) -> List[Dict]:
    """Get all pending transactions across all users"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT * FROM transactions 
        WHERE status = 'PENDING'
        ORDER BY started_at ASC
        LIMIT ?
        """, (limit,))
        
        rows = c.fetchall()
        
        transactions = []
        for row in rows:
            txn_data = dict(row)
            if txn_data.get("result"):
                txn_data["result"] = json.loads(txn_data["result"])
            transactions.append(txn_data)
        
        return transactions


def delete_transaction(txn_id: str) -> None:
    """Delete a transaction by ID"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM transactions WHERE txn_id = ?", (txn_id,))
        conn.commit()


def get_stats() -> Dict:
    """Get database statistics"""
    with get_db() as conn:
        c = conn.cursor()
        
        # Total transactions
        c.execute("SELECT COUNT(*) as count FROM transactions")
        total = c.fetchone()["count"]
        
        # By status
        c.execute("""
        SELECT status, COUNT(*) as count 
        FROM transactions 
        GROUP BY status
        """)
        by_status = {row["status"]: row["count"] for row in c.fetchall()}
        
        # Unique users
        c.execute("SELECT COUNT(DISTINCT user_id) as count FROM transactions")
        unique_users = c.fetchone()["count"]
        
        return {
            "total_transactions": total,
            "by_status": by_status,
            "unique_users": unique_users
        }


# Initialize on import
try:
    init_db()
except Exception as e:
    print(f"SQLite initialization will complete on first use: {e}")
