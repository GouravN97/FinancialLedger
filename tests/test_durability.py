"""Crash tests (TQ-12, NFR-5, NFR-6).

A child Python process does real ledger work against a database file and is
then killed with os._exit, which skips every cleanup step (no close, no
commit, no atexit), the same as the process being killed. The parent then
opens the file and checks what survived.

These run at the service level so they work before the HTTP server exists.
When the API is merged, the Quality owner can add the same check against a
running Uvicorn process.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from app.db.connection import connect
from app.ledger.reconciliation import reconcile

REPO_ROOT = Path(__file__).resolve().parents[1]

CHILD_SETUP = """
import json, os, sys
sys.path.insert(0, {root!r})
from app.db.connection import init_db
from app.ledger.hashing import request_fingerprint
from app.ledger.repository import LedgerRepository
from app.ledger.service import IdempotencyRequest, LedgerService

def idem(key, body):
    return IdempotencyRequest(key, request_fingerprint("POST", "/x", body))

conn = init_db({db!r})
svc = LedgerService(conn)
a = svc.create_wallet(svc.create_account("Asha")["id"], "INR")["id"]
b = svc.create_wallet(svc.create_account("Ravi")["id"], "INR")["id"]
svc.deposit(a, 50000, idem("deposit-0001", {{"n": 1}}))
"""


def run_child(db_path: Path, body: str) -> dict:
    code = CHILD_SETUP.format(root=str(REPO_ROOT), db=str(db_path)) + textwrap.dedent(body)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 137, f"child did not die as planned:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_committed_transfer_survives_a_hard_kill(tmp_path):
    db = tmp_path / "crash.db"
    info = run_child(db, """
        out = svc.transfer(a, b, 10000, idem("transfer-0001", {"n": 2}))
        assert out.status == 201
        print(json.dumps({"a": a, "b": b, "tx": out.body["transaction"]["id"]}), flush=True)
        os._exit(137)   # killed straight after the 201, connection never closed
    """)
    conn = connect(db)
    try:
        tx = conn.execute("SELECT type FROM transactions WHERE id = ?", (info["tx"],)).fetchone()
        assert tx is not None and tx["type"] == "TRANSFER"
        balances = dict(conn.execute("SELECT id, balance_minor FROM wallets WHERE id IN (?, ?)",
                                     (info["a"], info["b"])).fetchall())
        assert balances == {info["a"]: 40000, info["b"]: 10000}
        assert conn.execute("SELECT COUNT(*) FROM idempotency_keys WHERE key = 'transfer-0001'").fetchone()[0] == 1
        assert reconcile(conn)["status"] == "PASS"
    finally:
        conn.close()


def test_kill_in_the_middle_of_a_transfer_leaves_nothing(tmp_path):
    # NFR-6: killed after the transaction row and first entry are written, before COMMIT.
    db = tmp_path / "crash-mid.db"
    info = run_child(db, """
        real = LedgerRepository.insert_entry
        calls = []
        def dying_insert(self, tx_id, entry):
            calls.append(1)
            if len(calls) == 2:
                print(json.dumps({"a": a, "b": b}), flush=True)
                os._exit(137)   # half-written transfer, never committed
            return real(self, tx_id, entry)
        LedgerRepository.insert_entry = dying_insert
        svc.transfer(a, b, 10000, idem("transfer-0002", {"n": 3}))
    """)
    conn = connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'TRANSFER'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM idempotency_keys WHERE key = 'transfer-0002'").fetchone()[0] == 0
        balances = dict(conn.execute("SELECT id, balance_minor FROM wallets WHERE id IN (?, ?)",
                                     (info["a"], info["b"])).fetchall())
        assert balances == {info["a"]: 50000, info["b"]: 0}
        conn.execute("BEGIN IMMEDIATE")  # the dead process left no lock behind
        conn.execute("ROLLBACK")
        assert reconcile(conn)["status"] == "PASS"
    finally:
        conn.close()
