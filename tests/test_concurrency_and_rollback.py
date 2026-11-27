"""Race safety (FR-3.1, FR-3.3, FR-3.4) and rollback on failure (FR-3.2, TQ-2).

Concurrency tests use a temporary database FILE, never ':memory:', because
each connection to an in-memory SQLite database gets a separate database.
"""

import threading

import pytest

from app.db.connection import connect
from app.errors import LedgerError
from app.ledger.repository import LedgerRepository
from app.ledger.service import LedgerService
from tests.conftest import idem


def _transfer_body(src, dst, amount):
    return {"source_wallet_id": src, "destination_wallet_id": dst, "amount_minor": amount}


def test_twenty_simultaneous_transfers_never_overspend(db_path, funded, svc):
    # FR-3.4: B = 50000, N = 20, a = 10000  ->  exactly 5 succeed, 15 get 422, balance ends at 0.
    source, dest = funded(50000), funded(0, name="Ravi")
    results, start = [], threading.Barrier(20)

    def worker():
        conn = connect(db_path)
        try:
            service = LedgerService(conn)
            start.wait()
            body = _transfer_body(source, dest, 10000)
            try:
                results.append(service.transfer(source, dest, 10000, idem(body)).status)
            except LedgerError as err:
                results.append(err.code)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(results, key=str) == sorted([201] * 5 + [422] * 15, key=str), results
    assert svc.get_wallet(source)["balance_minor"] == 0
    assert svc.get_wallet(dest)["balance_minor"] == 50000


def test_lock_timeout_gives_service_busy_and_writes_nothing(db_path, funded, svc, conn):
    source, dest = funded(50000), funded(0, name="Ravi")
    holder = connect(db_path)
    holder.execute("BEGIN IMMEDIATE")  # someone else holds the write lock
    try:
        impatient = LedgerService(connect(db_path, busy_timeout_ms=200))
        with pytest.raises(LedgerError) as err:
            impatient.transfer(source, dest, 100, idem(_transfer_body(source, dest, 100)))
        assert err.value.code == "SERVICE_BUSY" and err.value.status == 503
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert svc.get_wallet(source)["balance_minor"] == 50000


# Every write step of a transfer; a crash at any of them must leave nothing behind.
FAILURE_POINTS = ["insert_transaction", "insert_entry", "set_balance", "insert_idempotency"]


@pytest.mark.parametrize("step", FAILURE_POINTS)
def test_failure_at_any_step_rolls_everything_back(monkeypatch, svc, conn, funded, step):
    source, dest = funded(50000), funded(0, name="Ravi")
    counts_before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("transactions", "ledger_entries", "idempotency_keys")}

    real = getattr(LedgerRepository, step)

    def explode(self, *args, **kwargs):
        if step in ("insert_entry", "set_balance") and not getattr(self, "_once", False):
            self._once = True  # let the first call succeed, fail on the second
            return real(self, *args, **kwargs)
        raise RuntimeError(f"injected failure in {step}")

    monkeypatch.setattr(LedgerRepository, step, explode)
    with pytest.raises(RuntimeError, match="injected"):
        svc.transfer(source, dest, 10000, idem(_transfer_body(source, dest, 10000)))
    monkeypatch.undo()

    for table, before in counts_before.items():
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == before, table
    assert svc.get_wallet(source)["balance_minor"] == 50000
    assert svc.get_wallet(dest)["balance_minor"] == 0
    assert not conn.in_transaction
