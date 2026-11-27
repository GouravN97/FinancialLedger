"""SQLite connection, migrations and seed data (SRS v1.1, Section 3.3, DB-3, FR-1.3)."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SUPPORTED_CURRENCIES = ("INR", "USD", "EUR")  # BR-3
INTERNAL_WALLET_KINDS = ("SYSTEM", "FX_CLEARING")  # FR-1.3
BUSY_TIMEOUT_MS = 5000  # FR-3.3


def connect(db_path: str | Path, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open a connection with the settings Section 3.3 requires.

    isolation_level=None turns off Python's implicit transactions, so the
    service layer controls them explicitly with BEGIN IMMEDIATE (FR-3.1).
    """
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=busy_timeout_ms / 1000,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA fullfsync = ON")  # only has an effect on macOS
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return conn


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply numbered migration files that have not run yet (DB-3).

    Each file runs in its own database transaction together with the
    row that records it, so a failed migration leaves nothing behind.
    Returns the names of the files applied.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
    )
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        if path.name in done:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in _split_statements(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(path.name)
    return applied


def seed_internal_wallets(conn: sqlite3.Connection) -> None:
    """Create one SYSTEM and one FX_CLEARING wallet per currency (FR-1.3).

    Safe to run repeatedly: the partial unique index on (kind, currency)
    makes INSERT OR IGNORE skip wallets that already exist.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        for currency in SUPPORTED_CURRENCIES:
            for kind in INTERNAL_WALLET_KINDS:
                conn.execute(
                    "INSERT OR IGNORE INTO wallets (id, account_id, currency, kind)"
                    " VALUES (?, NULL, ?, ?)",
                    (str(uuid.uuid4()), currency, kind),
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open the database, bring the schema up to date and seed it."""
    conn = connect(db_path)
    apply_migrations(conn)
    seed_internal_wallets(conn)
    return conn


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into complete statements.

    sqlite3.complete_statement() understands trigger bodies
    (BEGIN ... END;), so semicolons inside triggers are handled.
    """
    statements, buffer = [], ""
    for line in sql.splitlines(keepends=True):
        if line.lstrip().startswith("--") and not buffer.strip():
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError(f"Incomplete SQL statement at end of migration: {buffer[:80]!r}")
    return statements
