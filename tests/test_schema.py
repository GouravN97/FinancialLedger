"""Schema tests for 001_init.sql (SRS v1.1: DB-1 to DB-4, FR-1.3, FR-3.5, FR-4.1, NFR-8, BR-2, BR-7)."""

import sqlite3
import uuid

import pytest

from app.db.connection import apply_migrations, connect, init_db

ZERO_HASH = "0" * 64


@pytest.fixture
def conn(tmp_path):
    # Always a fresh temporary file, never LEDGER_DB_PATH (NFR-7, TQ-5).
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


def new_id():
    return str(uuid.uuid4())


def make_user_wallet(conn, currency="INR", balance=0):
    account_id = new_id()
    conn.execute("INSERT INTO accounts (id, name) VALUES (?, ?)", (account_id, "Asha"))
    wallet_id = new_id()
    conn.execute(
        "INSERT INTO wallets (id, account_id, currency, kind, balance_minor) VALUES (?, ?, ?, 'USER', ?)",
        (wallet_id, account_id, currency, balance),
    )
    return account_id, wallet_id


def make_transaction(conn, seq=1, type_="DEPOSIT", **extra):
    tx_id = new_id()
    cols = {"id": tx_id, "seq": seq, "type": type_, "prev_hash": ZERO_HASH, "hash": f"{seq:064x}", **extra}
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    conn.execute(f"INSERT INTO transactions ({names}) VALUES ({marks})", tuple(cols.values()))
    return tx_id


def make_admin(conn):
    admin_id = new_id()
    conn.execute("INSERT INTO admin_keys (id, name, key_hash) VALUES (?, 'admin', ?)", (admin_id, "a" * 64))
    return admin_id


# ---------- connection settings (Section 3.3) ----------

def test_connection_pragmas(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


# ---------- tables and migrations (DB-1, DB-3) ----------

def test_seven_tables_exist(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {"accounts", "wallets", "admin_keys", "fx_rates", "transactions", "ledger_entries", "idempotency_keys"}
    assert expected <= tables


def test_migrations_run_once(tmp_path):
    db = tmp_path / "m.db"
    init_db(db).close()
    c = connect(db)
    assert apply_migrations(c) == []  # nothing new to apply the second time
    c.close()


# ---------- internal wallets (FR-1.3) ----------

def test_one_system_and_one_fx_wallet_per_currency(conn):
    rows = conn.execute(
        "SELECT kind, currency, COUNT(*) FROM wallets WHERE kind <> 'USER' GROUP BY kind, currency"
    ).fetchall()
    assert {(r[0], r[1]): r[2] for r in rows} == {
        (k, c): 1 for k in ("SYSTEM", "FX_CLEARING") for c in ("INR", "USD", "EUR")
    }


def test_seeding_twice_creates_no_duplicates(tmp_path):
    db = tmp_path / "s.db"
    init_db(db).close()
    c = init_db(db)
    assert c.execute("SELECT COUNT(*) FROM wallets WHERE kind <> 'USER'").fetchone()[0] == 6
    c.close()


def test_internal_wallets_have_no_account(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO wallets (id, account_id, currency, kind) VALUES (?, NULL, 'INR', 'USER')", (new_id(),))


# ---------- wallet rules (FR-1.2, BR-2, BR-3, FR-3.5) ----------

def test_one_wallet_per_account_per_currency(conn):
    account_id, _ = make_user_wallet(conn, "INR")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO wallets (id, account_id, currency, kind) VALUES (?, ?, 'INR', 'USER')",
            (new_id(), account_id),
        )


def test_unsupported_currency_rejected(conn):
    account_id = new_id()
    conn.execute("INSERT INTO accounts (id, name) VALUES (?, 'Ravi')", (account_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO wallets (id, account_id, currency, kind) VALUES (?, ?, 'GBP', 'USER')",
            (new_id(), account_id),
        )


def test_user_wallet_cannot_go_negative(conn):
    _, wallet_id = make_user_wallet(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE wallets SET balance_minor = -1 WHERE id = ?", (wallet_id,))


def test_system_wallet_can_go_negative(conn):
    conn.execute("UPDATE wallets SET balance_minor = -50000 WHERE kind = 'SYSTEM' AND currency = 'INR'")
    assert conn.execute(
        "SELECT balance_minor FROM wallets WHERE kind = 'SYSTEM' AND currency = 'INR'"
    ).fetchone()[0] == -50000


# ---------- integer money (C-3, NFR-8, DB-2) ----------

def test_fractional_amount_rejected(conn):
    _, wallet_id = make_user_wallet(conn)
    tx_id = make_transaction(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ledger_entries (transaction_id, wallet_id, direction, amount_minor, balance_after)"
            " VALUES (?, ?, 'CREDIT', 100.5, 100)",
            (tx_id, wallet_id),
        )


@pytest.mark.parametrize("amount", [0, -100])
def test_non_positive_amount_rejected(conn, amount):
    _, wallet_id = make_user_wallet(conn)
    tx_id = make_transaction(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ledger_entries (transaction_id, wallet_id, direction, amount_minor, balance_after)"
            " VALUES (?, ?, 'CREDIT', ?, 0)",
            (tx_id, wallet_id, amount),
        )


# ---------- transactions and reversals (FR-4.2 to FR-4.4, BR-8) ----------

def test_sequence_numbers_are_unique(conn):
    make_transaction(conn, seq=1)
    with pytest.raises(sqlite3.IntegrityError):
        make_transaction(conn, seq=1)


def test_reversal_needs_admin_and_reason(conn):
    original = make_transaction(conn, seq=1)
    with pytest.raises(sqlite3.IntegrityError):
        make_transaction(conn, seq=2, type_="REVERSAL", reverses_id=original)


def test_transaction_reversed_at_most_once(conn):
    admin_id = make_admin(conn)
    original = make_transaction(conn, seq=1)
    make_transaction(conn, seq=2, type_="REVERSAL", reverses_id=original, admin_id=admin_id, reason="wrong amount")
    with pytest.raises(sqlite3.IntegrityError):
        make_transaction(conn, seq=3, type_="REVERSAL", reverses_id=original, admin_id=admin_id, reason="again")


def test_non_reversal_cannot_point_at_another_transaction(conn):
    original = make_transaction(conn, seq=1)
    with pytest.raises(sqlite3.IntegrityError):
        make_transaction(conn, seq=2, type_="TRANSFER", reverses_id=original)


# ---------- immutability (FR-4.1, BR-7) ----------

def test_ledger_entries_cannot_be_updated_or_deleted(conn):
    _, wallet_id = make_user_wallet(conn)
    tx_id = make_transaction(conn)
    conn.execute(
        "INSERT INTO ledger_entries (transaction_id, wallet_id, direction, amount_minor, balance_after)"
        " VALUES (?, ?, 'CREDIT', 100, 100)",
        (tx_id, wallet_id),
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE ledger_entries SET amount_minor = 999")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM ledger_entries")


def test_transactions_cannot_be_updated_or_deleted(conn):
    make_transaction(conn)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE transactions SET type = 'TRANSFER'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM transactions")


def test_idempotency_keys_cannot_be_updated_or_deleted(conn):
    conn.execute(
        "INSERT INTO idempotency_keys (key, fingerprint, status_code, response_body) VALUES (?, ?, 422, '{}')",
        ("key-12345", "f" * 64),
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE idempotency_keys SET status_code = 201")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM idempotency_keys")


def test_fx_rates_cannot_be_updated_or_deleted(conn):
    admin_id = make_admin(conn)
    conn.execute(
        "INSERT INTO fx_rates (id, base_currency, quote_currency, rate_scaled, admin_id) VALUES (?, 'USD', 'INR', 88123456, ?)",
        (new_id(), admin_id),
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE fx_rates SET rate_scaled = 1")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM fx_rates")


def test_admin_keys_can_be_revoked(conn):
    admin_id = make_admin(conn)
    conn.execute("UPDATE admin_keys SET revoked_at = '2026-11-15T00:00:00Z' WHERE id = ?", (admin_id,))
    assert conn.execute("SELECT revoked_at FROM admin_keys WHERE id = ?", (admin_id,)).fetchone()[0]


def test_accounts_and_wallets_cannot_be_deleted(conn):
    account_id, wallet_id = make_user_wallet(conn)
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        conn.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def test_foreign_keys_enforced(conn):
    tx_id = make_transaction(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ledger_entries (transaction_id, wallet_id, direction, amount_minor, balance_after)"
            " VALUES (?, ?, 'CREDIT', 100, 100)",
            (tx_id, new_id()),
        )
