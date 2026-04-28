import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get("ESCROW_DB", "escrow.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                wallet TEXT,
                bank TEXT,
                balance REAL NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                buyer_id INTEGER,
                amount REAL NOT NULL,
                fee REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(seller_id) REFERENCES users(id),
                FOREIGN KEY(buyer_id) REFERENCES users(id)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS disputes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id INTEGER NOT NULL,
                opened_by INTEGER NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                resolution TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(deal_id) REFERENCES deals(id)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )


def now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


# ---------- USERS ----------

def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def upsert_user(user_id: int, username: Optional[str]) -> Dict[str, Any]:
    existing = get_user(user_id)
    if existing:
        if username and existing.get("username") != username:
            with get_conn() as conn:
                conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
        return get_user(user_id)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (id, username, balance, created_at) VALUES (?, ?, 0, ?)",
            (user_id, username, now()),
        )
    return get_user(user_id)


def set_wallet(user_id: int, wallet: str, bank: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET wallet = ?, bank = ? WHERE id = ?",
            (wallet, bank, user_id),
        )


def add_balance(user_id: int, amount: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (amount, user_id),
        )


def list_users() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def set_admin(user_id: int, is_admin: bool) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))


# ---------- DEALS ----------

def create_deal(seller_id: int, amount: float, fee: float) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO deals (seller_id, amount, fee, status, created_at, updated_at)
            VALUES (?, ?, ?, 'created', ?, ?)
            """,
            (seller_id, amount, fee, now(), now()),
        )
        return cur.lastrowid


def get_deal(deal_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
        return dict(row) if row else None


def update_deal_status(deal_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE deals SET status = ?, updated_at = ? WHERE id = ?",
            (status, now(), deal_id),
        )


def set_buyer(deal_id: int, buyer_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE deals SET buyer_id = ?, status = 'waiting_payment', updated_at = ? WHERE id = ?",
            (buyer_id, now(), deal_id),
        )


def list_deals() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM deals ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def list_user_deals(user_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM deals WHERE seller_id = ? OR buyer_id = ? ORDER BY created_at DESC",
            (user_id, user_id),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- DISPUTES ----------

def create_dispute(deal_id: int, opened_by: int, reason: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO disputes (deal_id, opened_by, reason, status, created_at)
            VALUES (?, ?, ?, 'open', ?)
            """,
            (deal_id, opened_by, reason, now()),
        )
        return cur.lastrowid


def get_dispute_for_deal(deal_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM disputes WHERE deal_id = ? ORDER BY created_at DESC LIMIT 1",
            (deal_id,),
        ).fetchone()
        return dict(row) if row else None


def resolve_dispute(dispute_id: int, status: str, resolution: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE disputes SET status = ?, resolution = ? WHERE id = ?",
            (status, resolution, dispute_id),
        )


def list_disputes() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM disputes ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


# ---------- LOGS ----------

def add_log(action: str, details: str = "", user_id: Optional[int] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, action, details, now()),
        )


def list_logs(limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
