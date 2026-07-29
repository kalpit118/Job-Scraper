"""
database/db.py
--------------
SQLite data-access layer for the job aggregation system.

Responsibilities
----------------
- Create and migrate the ``jobs`` table.
- Insert new jobs (idempotent via composite unique constraint).
- Track which jobs have been successfully notified via Telegram.
- Retry unnotified jobs on every pipeline run (guarantees delivery).
- Query stored jobs.

All database interactions use parameterised queries to prevent SQL injection.
The database file path is read from the environment (defaults to ``database/jobs.db``).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from scraper.base import Job
from utils.logger import logger

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(os.getenv("DB_PATH", "database/jobs.db"))

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    location    TEXT    NOT NULL,
    salary      TEXT    DEFAULT 'Not Mentioned',
    experience  TEXT    DEFAULT 'Unknown',
    mode        TEXT    DEFAULT 'Unknown',
    url         TEXT    NOT NULL,
    logo        TEXT    DEFAULT '',
    posted      TEXT    DEFAULT '',
    created_at  TEXT    NOT NULL,
    dedup_key   TEXT    NOT NULL,
    notified    INTEGER DEFAULT 0,
    UNIQUE (dedup_key)
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs (dedup_key);
"""

_CREATE_NOTIFY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs (notified);
"""

_MIGRATION_ADD_NOTIFIED = """
ALTER TABLE jobs ADD COLUMN notified INTEGER DEFAULT 0;
"""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

@contextmanager
def _get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager yielding a configured :class:`sqlite3.Connection`.

    - Row factory set to :class:`sqlite3.Row` for dict-like access.
    - WAL journal mode for better concurrent read performance.
    - Foreign keys enforced.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists in *table*."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Initialise the database: create tables, apply migrations, and build indexes.

    Safe to call on every startup — uses ``IF NOT EXISTS`` guards and
    column-existence checks for backward-compatible migrations.
    """
    with _get_connection() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)

        # Migration: add `notified` column to existing databases
        if not _column_exists(conn, "jobs", "notified"):
            logger.info("Migrating DB: adding 'notified' column to jobs table")
            conn.execute(_MIGRATION_ADD_NOTIFIED)

        conn.execute(_CREATE_NOTIFY_INDEX_SQL)

    logger.info(f"Database ready at {DB_PATH.resolve()}")


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def insert_job(job: Job) -> bool:
    """
    Persist a :class:`Job` to the database.

    Uses ``INSERT OR IGNORE`` so that duplicate keys (same company + role
    + location) are silently skipped.

    Returns:
        ``True`` if the row was newly inserted, ``False`` if it already existed.
    """
    sql = """
    INSERT OR IGNORE INTO jobs
        (company, role, location, salary, experience, mode, url, logo, posted, created_at, dedup_key, notified)
    VALUES
        (:company, :role, :location, :salary, :experience, :mode, :url, :logo, :posted, :created_at, :dedup_key, 0)
    """
    params = {
        "company": job.company,
        "role": job.role,
        "location": job.location,
        "salary": job.salary,
        "experience": job.experience,
        "mode": job.work_mode,
        "url": job.apply_url,
        "logo": job.logo_url,
        "posted": job.posted_date,
        "created_at": job.created_at,
        "dedup_key": job.dedup_key(),
    }
    with _get_connection() as conn:
        cursor = conn.execute(sql, params)
        inserted = cursor.rowcount > 0
    if inserted:
        logger.debug(f"Inserted: [{job.company}] {job.role} @ {job.location}")
    return inserted


def mark_notified(job_id: int) -> None:
    """
    Mark a job as successfully notified in Telegram.

    Args:
        job_id: The ``id`` primary key of the job row.
    """
    with _get_connection() as conn:
        conn.execute("UPDATE jobs SET notified = 1 WHERE id = ?", (job_id,))


def get_pending_notifications() -> list[dict]:
    """
    Return all jobs that have NOT yet been successfully notified.

    These are jobs that were stored in a previous run where Telegram
    was unavailable.  Ordered oldest-first so notifications arrive
    in chronological order.
    """
    sql = "SELECT * FROM jobs WHERE notified = 0 ORDER BY id ASC"
    with _get_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def is_duplicate(job: Job) -> bool:
    """
    Return ``True`` if a job with the same dedup key already exists.

    Args:
        job: The candidate :class:`Job` to check.
    """
    sql = "SELECT 1 FROM jobs WHERE dedup_key = ? LIMIT 1"
    with _get_connection() as conn:
        row = conn.execute(sql, (job.dedup_key(),)).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_all_jobs() -> list[dict]:
    """Return all stored jobs as a list of dicts (most-recent first)."""
    sql = "SELECT * FROM jobs ORDER BY id DESC"
    with _get_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def get_jobs_since(iso_timestamp: str) -> list[dict]:
    """
    Return jobs inserted on or after *iso_timestamp*.

    Args:
        iso_timestamp: ISO-8601 UTC string, e.g. ``"2024-01-01T00:00:00+00:00"``.
    """
    sql = "SELECT * FROM jobs WHERE created_at >= ? ORDER BY id DESC"
    with _get_connection() as conn:
        rows = conn.execute(sql, (iso_timestamp,)).fetchall()
    return [dict(row) for row in rows]


def count_jobs() -> int:
    """Return the total number of jobs in the database."""
    with _get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    return row[0] if row else 0


def count_pending() -> int:
    """Return the number of jobs awaiting Telegram notification."""
    with _get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM jobs WHERE notified = 0").fetchone()
    return row[0] if row else 0
