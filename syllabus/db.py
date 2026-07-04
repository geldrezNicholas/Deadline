"""SQLite storage for Google OAuth tokens, one row per browser session.

The sid comes from the visitor's signed session cookie.
"""

from __future__ import annotations

import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.db")

# tokens count as expired this many seconds early
EXPIRY_BUFFER = 60

# token rows untouched for this long get deleted
STALE_AFTER_DAYS = 90


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        # drop the old single-user schema if it's still around
        cols = [r[1] for r in conn.execute("PRAGMA table_info(google_tokens)")]
        if cols and "sid" not in cols:
            conn.execute("DROP TABLE google_tokens")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS google_tokens (
                sid           TEXT PRIMARY KEY,
                access_token  TEXT NOT NULL,
                refresh_token TEXT,
                expires_at    REAL NOT NULL,
                scope         TEXT,
                updated_at    REAL NOT NULL
            )
            """
        )
        conn.execute(
            "DELETE FROM google_tokens WHERE updated_at < ?",
            (time.time() - STALE_AFTER_DAYS * 86400,),
        )


def save_tokens(sid: str, access_token: str, refresh_token: str | None,
                expires_in: int, scope: str | None) -> None:
    """Upsert this session's token row.

    COALESCE keeps the existing refresh_token when the new one is null,
    which happens on every token refresh.
    """
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO google_tokens (sid, access_token, refresh_token, expires_at, scope, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sid) DO UPDATE SET
                access_token  = excluded.access_token,
                refresh_token = COALESCE(excluded.refresh_token, google_tokens.refresh_token),
                expires_at    = excluded.expires_at,
                scope         = excluded.scope,
                updated_at    = excluded.updated_at
            """,
            (sid, access_token, refresh_token, now + expires_in - EXPIRY_BUFFER, scope, now),
        )


def get_tokens(sid: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM google_tokens WHERE sid = ?", (sid,)
        ).fetchone()
    return dict(row) if row else None


def delete_tokens(sid: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM google_tokens WHERE sid = ?", (sid,))


def access_token_expired(tokens: dict) -> bool:
    return time.time() >= tokens["expires_at"]
