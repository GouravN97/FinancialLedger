"""Repository layer: the only ledger code that issues SQL (NFR-16, C-4).

Every statement uses parameter binding (NFR-12). Functions here contain no
money rules; they read and write rows and leave decisions to the service.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional


class LedgerRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- database transactions ----------

    def begin_immediate(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    def begin_read(self) -> None:
        # A deferred transaction: in WAL mode its first read fixes one
        # consistent snapshot for every later read in it (FR-5.1).
        self.conn.execute("BEGIN")

    def commit(self) -> None:
        self.conn.execute("COMMIT")

    def rollback(self) -> None:
        if self.conn.in_transaction:
            self.conn.execute("ROLLBACK")

    def savepoint(self, name: str) -> None:
        self.conn.execute(f"SAVEPOINT {name}")

    def rollback_to(self, name: str) -> None:
        self.conn.execute(f"ROLLBACK TO {name}")

    def release(self, name: str) -> None:
        self.conn.execute(f"RELEASE {name}")

    # ---------- accounts and wallets ----------

    def insert_account(self, account_id: str, name: str, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO accounts (id, name, created_at) VALUES (?, ?, ?)",
            (account_id, name, created_at),
        )

    def get_account(self, account_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()

    def insert_wallet(self, wallet_id: str, account_id: str, currency: str, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO wallets (id, account_id, currency, kind, balance_minor, created_at)"
            " VALUES (?, ?, ?, 'USER', 0, ?)",
            (wallet_id, account_id, currency, created_at),
        )

    def find_user_wallet(self, account_id: str, currency: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM wallets WHERE account_id = ? AND currency = ?", (account_id, currency)
        ).fetchone()

    def get_wallet(self, wallet_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,)).fetchone()

    def get_internal_wallet(self, kind: str, currency: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM wallets WHERE kind = ? AND currency = ?", (kind, currency)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"{kind} wallet for {currency} is missing; run init_db first")
        return row

    def set_balance(self, wallet_id: str, balance_minor: int) -> None:
        self.conn.execute("UPDATE wallets SET balance_minor = ? WHERE id = ?", (balance_minor, wallet_id))

    def all_wallets(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM wallets ORDER BY created_at, id").fetchall()

    # ---------- transactions and entries ----------

    def last_transaction(self) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT seq, hash FROM transactions ORDER BY seq DESC LIMIT 1").fetchone()

    def insert_transaction(self, tx: dict) -> None:
        self.conn.execute(
            "INSERT INTO transactions (id, seq, type, reverses_id, fx_rate_id, admin_id, reason,"
            " prev_hash, hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tx["id"], tx["seq"], tx["type"], tx["reverses_id"], tx["fx_rate_id"], tx["admin_id"],
             tx["reason"], tx["prev_hash"], tx["hash"], tx["created_at"]),
        )

    def insert_entry(self, transaction_id: str, entry: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO ledger_entries (transaction_id, wallet_id, direction, amount_minor, balance_after)"
            " VALUES (?, ?, ?, ?, ?)",
            (transaction_id, entry["wallet_id"], entry["direction"], entry["amount_minor"], entry["balance_after"]),
        )
        return cur.lastrowid

    def get_transaction(self, transaction_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()

    def find_reversal_of(self, transaction_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM transactions WHERE reverses_id = ?", (transaction_id,)).fetchone()

    def entries_of(self, transaction_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY id", (transaction_id,)
        ).fetchall()

    def wallet_entries(self, wallet_id: str, after_id: Optional[int], limit: int) -> list[sqlite3.Row]:
        # Writes are serialised (FR-3.1), so entry ids grow in sequence order.
        return self.conn.execute(
            "SELECT e.*, t.seq, t.type, t.created_at FROM ledger_entries e"
            " JOIN transactions t ON t.id = e.transaction_id"
            " WHERE e.wallet_id = ? AND e.id > ? ORDER BY e.id LIMIT ?",
            (wallet_id, after_id or 0, limit),
        ).fetchall()

    def all_transactions(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM transactions ORDER BY seq").fetchall()

    def all_entries(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT e.*, w.currency, w.kind FROM ledger_entries e JOIN wallets w ON w.id = e.wallet_id ORDER BY e.id"
        ).fetchall()

    # ---------- idempotency ----------

    def get_idempotency(self, key: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM idempotency_keys WHERE key = ?", (key,)).fetchone()

    def insert_idempotency(self, key: str, fingerprint: str, status_code: int, response_body: str,
                           transaction_id: Optional[str], created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO idempotency_keys (key, fingerprint, status_code, response_body, transaction_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (key, fingerprint, status_code, response_body, transaction_id, created_at),
        )

    # ---------- admin keys (read only here) ----------

    def admin_exists(self, admin_id: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM admin_keys WHERE id = ? AND revoked_at IS NULL", (admin_id,)
        ).fetchone() is not None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]
