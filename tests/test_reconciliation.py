"""Reconciliation (FR-5.1 to FR-5.4) and the tamper test (TQ-10)."""

from app.ledger.reconciliation import reconcile
from tests.conftest import idem

HISTORY_TRIGGERS = ("trg_entries_no_update", "trg_entries_no_delete",
                    "trg_transactions_no_update", "trg_transactions_no_delete")


def _transfer(svc, a, b, amount):
    body = {"source_wallet_id": a, "destination_wallet_id": b, "amount_minor": amount}
    return svc.transfer(a, b, amount, idem(body)).body


def _drop_triggers(conn):
    # Simulates someone editing the database file directly, bypassing the API.
    for name in HISTORY_TRIGGERS:
        conn.execute(f"DROP TRIGGER {name}")


def test_empty_ledger_passes(conn):
    report = reconcile(conn)
    assert report["status"] == "PASS" and report["transactions_checked"] == 0


def test_pass_after_normal_activity(svc, conn, funded, make_admin):
    admin = make_admin()
    a, b = funded(50000), funded(0, name="Ravi")
    usd = funded(9900, currency="USD", name="Sam")
    original = _transfer(svc, a, b, 10000)["transaction"]["id"]
    _transfer(svc, a, b, 2500)
    svc.reverse(original, "test", admin, idem({"r": 1}))
    report = reconcile(conn)
    assert report["status"] == "PASS", report
    assert report["totals"]["INR"] == {"debits_minor": 72500, "credits_minor": 72500}
    assert report["totals"]["USD"] == {"debits_minor": 9900, "credits_minor": 9900}
    assert report["transactions_checked"] == 5 and report["latest_seq"] == 5
    assert all(c["passed"] for c in report["checks"].values())
    assert usd


def test_reconciliation_writes_nothing(svc, conn, funded):
    funded(50000)
    before = conn.total_changes
    reconcile(conn)
    assert conn.total_changes == before and not conn.in_transaction


def test_tampered_amount_is_detected(svc, conn, funded):
    # TQ-10: edit one entry directly; reconciliation must FAIL and name the transaction.
    a, b = funded(50000), funded(0, name="Ravi")
    target = _transfer(svc, a, b, 10000)["transaction"]
    _transfer(svc, a, b, 500)
    _drop_triggers(conn)
    conn.execute("UPDATE ledger_entries SET amount_minor = 1 WHERE transaction_id = ? AND direction = 'CREDIT'",
                 (target["id"],))
    report = reconcile(conn)
    assert report["status"] == "FAIL"
    g = report["checks"]["g_hash_chain_intact"]
    assert not g["passed"] and g["discrepancies"][0]["transaction_id"] == target["id"]
    assert not report["checks"]["a_transactions_balance"]["passed"]


def test_balanced_tamper_still_caught_by_hash(svc, conn, funded):
    # Changing both sides keeps debits = credits, so only the hash chain can catch it.
    a, b = funded(50000), funded(0, name="Ravi")
    target = _transfer(svc, a, b, 10000)["transaction"]
    _drop_triggers(conn)
    conn.execute("UPDATE ledger_entries SET amount_minor = 20000 WHERE transaction_id = ?", (target["id"],))
    report = reconcile(conn)
    assert report["checks"]["a_transactions_balance"]["passed"]
    assert report["checks"]["g_hash_chain_intact"]["discrepancies"][0]["transaction_id"] == target["id"]
    assert report["status"] == "FAIL"


def test_stored_balance_mismatch_detected(svc, conn, funded):
    a = funded(50000)
    conn.execute("UPDATE wallets SET balance_minor = 99999 WHERE id = ?", (a,))
    report = reconcile(conn)
    c = report["checks"]["c_wallet_balances_match"]
    assert report["status"] == "FAIL" and c["discrepancies"][0] == {"wallet_id": a, "expected": 50000, "actual": 99999}


def test_deleted_transaction_detected(svc, conn, funded):
    a, b = funded(50000), funded(0, name="Ravi")
    middle = _transfer(svc, a, b, 100)["transaction"]["id"]
    _transfer(svc, a, b, 200)
    _drop_triggers(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM ledger_entries WHERE transaction_id = ?", (middle,))
    conn.execute("DELETE FROM transactions WHERE id = ?", (middle,))
    report = reconcile(conn)
    assert report["status"] == "FAIL"
    assert not report["checks"]["f_no_sequence_gaps"]["passed"]
    assert not report["checks"]["g_hash_chain_intact"]["passed"]
