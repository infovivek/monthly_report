from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH

_lock = threading.Lock()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db():
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clubs (
                club_no TEXT PRIMARY KEY,
                club_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                club_no TEXT NOT NULL,
                name TEXT NOT NULL,
                mobile TEXT,
                mobile_digits TEXT,
                email TEXT,
                rotary_id TEXT,
                extra_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (club_no) REFERENCES clubs(club_no)
            );

            CREATE INDEX IF NOT EXISTS idx_members_club ON members(club_no);
            CREATE INDEX IF NOT EXISTS idx_members_rotary ON members(rotary_id);
            CREATE INDEX IF NOT EXISTS idx_members_mobile ON members(club_no, mobile_digits);

            CREATE TABLE IF NOT EXISTS send_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                club_no TEXT,
                club_name TEXT,
                month_label TEXT,
                pdf_filename TEXT,
                pdf_path TEXT,
                pdf_url TEXT,
                status TEXT NOT NULL,
                total INTEGER NOT NULL DEFAULT 0,
                sent INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS send_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                member_id INTEGER,
                name TEXT,
                club_name TEXT,
                mobile TEXT,
                wa_to TEXT,
                status TEXT NOT NULL,
                skip_reason TEXT,
                http_status INTEGER,
                request_json TEXT,
                response_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES send_jobs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_logs_job ON send_logs(job_id);
            CREATE INDEX IF NOT EXISTS idx_logs_status ON send_logs(status);
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(clubs)")}
        if "pdf_url" not in cols:
            conn.execute("ALTER TABLE clubs ADD COLUMN pdf_url TEXT")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def list_clubs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.club_no, c.club_name, c.pdf_url,
               COUNT(m.id) AS member_count,
               SUM(CASE WHEN m.mobile_digits IS NOT NULL AND length(m.mobile_digits)=10 THEN 1 ELSE 0 END) AS sendable_count
        FROM clubs c
        LEFT JOIN members m ON m.club_no = c.club_no
        GROUP BY c.club_no
        ORDER BY c.club_name COLLATE NOCASE
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_club(conn: sqlite3.Connection, club_no: str) -> dict | None:
    row = conn.execute(
        "SELECT club_no, club_name, pdf_url FROM clubs WHERE club_no = ?", (club_no,)
    ).fetchone()
    return row_to_dict(row)


def list_members(conn: sqlite3.Connection, club_no: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, club_no, name, mobile, mobile_digits, email, rotary_id
        FROM members
        WHERE club_no = ?
        ORDER BY name COLLATE NOCASE
        """,
        (club_no,),
    ).fetchall()
    return [dict(r) for r in rows]


def member_counts(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT COUNT(*) AS n FROM members").fetchone()
    clubs = conn.execute("SELECT COUNT(*) AS n FROM clubs").fetchone()
    with_file = conn.execute(
        "SELECT COUNT(*) AS n FROM clubs WHERE pdf_url IS NOT NULL AND trim(pdf_url) != ''"
    ).fetchone()
    return {"members": row["n"], "clubs": clubs["n"], "clubs_with_file": with_file["n"]}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def create_job(conn, *, club_no, club_name, month_label, pdf_filename, pdf_path, pdf_url, total):
    cur = conn.execute(
        """
        INSERT INTO send_jobs (
            club_no, club_name, month_label, pdf_filename, pdf_path, pdf_url,
            status, total, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
        """,
        (club_no, club_name, month_label, pdf_filename, pdf_path, pdf_url, total, utcnow()),
    )
    return cur.lastrowid


def get_job(conn, job_id: int):
    return row_to_dict(conn.execute("SELECT * FROM send_jobs WHERE id = ?", (job_id,)).fetchone())


def list_jobs(conn, limit: int = 30) -> list[dict]:
    rows = conn.execute("SELECT * FROM send_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_job_logs(conn, job_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, name, mobile, wa_to, status, skip_reason, http_status, created_at
        FROM send_logs WHERE job_id = ? ORDER BY id
        """,
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_logs(conn, status: str | None = None, limit: int = 200) -> list[dict]:
    sql = """
        SELECT l.*, j.month_label, j.club_name AS job_club
        FROM send_logs l
        JOIN send_jobs j ON j.id = l.job_id
        WHERE 1=1
    """
    params: list = []
    if status:
        sql += " AND l.status = ?"
        params.append(status)
    sql += " ORDER BY l.id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
