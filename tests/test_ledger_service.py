"""Service tests for FR-1, FR-2 and FR-4 (TQ-1, TQ-3 at service level, TQ-4)."""

import uuid

import pytest

from app.errors import LedgerError
from app.ledger.hashing import GENESIS_HASH
from app.ledger.service import IdempotencyRequest
from tests.conftest import idem, key


def balance(svc, wallet_id):
    return svc.get_wallet(wallet_id)["balance_minor"]


def system_balance(conn, currency="INR"):
    return conn.execute("SELECT balance_minor FROM wallets WHERE kind='SYSTEM' AND currency=?",
                        (currency,)).fetchone()[0]


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def transfer(svc, src, dst, amount, k=None):
    body = {"source_wallet_id": src, "destination_wallet_id": dst, "amount_minor": amount}
    return svc.transfer(src, dst, amount, idem(body, k=k))


# ================= FR-1: accounts, wallets, deposits =================

def test_create_account_and_wallet(svc):
    account = svc.create_account("Asha")
    uuid.UUID(account["id"])
    wallet = svc.create_wallet(account["id"], "INR")
    assert svc.get_wallet(wallet["id"])["balance_minor"] == 0


@pytest.mark.parametrize("name", ["", "x" * 101, None, 5])
def test_account_name_validated(svc, name):
    with pytest.raises(LedgerError) as err:
        svc.create_account(name)
    assert err.value.code == "VALIDATION_ERROR"


def test_one_wallet_per_currency(svc):
    account = svc.create_account("Asha")
    svc.create_wallet(account["id"], "INR")
    svc.create_wallet(account["id"], "USD")
    with pytest.raises(LedgerError) as err:
        svc.create_wallet(account["id"], "INR")
    assert err.value.code == "WALLET_EXISTS" and err.value.status == 409


def test_wallet_for_unknown_account(svc):
    with pytest.raises(LedgerError) as err:
        svc.create_wallet(str(uuid.uuid4()), "INR")
    assert err.value.code == "ACCOUNT_NOT_FOUND"


def test_bad_and_unknown_ids(svc):
    with pytest.raises(LedgerError) as err:
        svc.get_wallet("not-a-uuid")
    assert err.value.status == 400
    with pytest.raises(LedgerError) as err:
        svc.get_wallet(str(uuid.uuid4()))
    assert err.value.code == "WALLET_NOT_FOUND"


def test_deposit_debits_system_wallet_and_credits_user(svc, conn, funded):
    wallet = funded(50000)
    assert balance(svc, wallet) == 50000
    assert system_balance(conn) == -50000  # BR-2: only internal wallets may go negative


def test_deposit_into_system_wallet_refused_and_stored(svc, conn):
    system_id = conn.execute("SELECT id FROM wallets WHERE kind='SYSTEM' AND currency='INR'").fetchone()[0]
    out = svc.deposit(system_id, 100, idem({"amount_minor": 100}))
    assert out.status == 422 and out.body["error"]["code"] == "SYSTEM_WALLET_NOT_ALLOWED"
    assert count(conn, "transactions") == 0


# ================= FR-2: transfers and idempotency =================

def test_transfer_moves_money_and_returns_balances(svc, funded):
    a, b = funded(50000), funded(0, name="Ravi")
    out = transfer(svc, a, b, 10000)
    assert out.status == 201 and not out.replayed
    assert out.body["balances"] == {a: 40000, b: 10000}
    assert [e["direction"] for e in out.body["entries"]] == ["DEBIT", "CREDIT"]
    assert balance(svc, a) == 40000 and balance(svc, b) == 10000


def test_retry_with_same_key_replays_and_moves_nothing(svc, conn, funded):
    a, b = funded(50000), funded(0, name="Ravi")
    k = key()
    first = transfer(svc, a, b, 10000, k=k)
    before = count(conn, "ledger_entries")
    again = transfer(svc, a, b, 10000, k=k)
    assert again.replayed and again.status == 201 and again.body == first.body
    assert count(conn, "ledger_entries") == before
    assert balance(svc, a) == 40000


def test_same_key_different_body_is_409_and_not_stored(svc, conn, funded):
    a, b = funded(50000), funded(0, name="Ravi")
    k = key()
    transfer(svc, a, b, 10000, k=k)
    with pytest.raises(LedgerError) as err:
        transfer(svc, a, b, 20000, k=k)
    assert err.value.code == "IDEMPOTENCY_KEY_REUSED" and err.value.status == 409
    assert balance(svc, a) == 40000


def test_business_rejection_is_stored_and_replayed(svc, conn, funded):
    # FR-2.3: a 422 is stored, so the same key keeps giving the same answer (A-2).
    a, b = funded(5000), funded(0, name="Ravi")
    k = key()
    first = transfer(svc, a, b, 10000, k=k)
    assert first.status == 422 and first.body["error"]["code"] == "INSUFFICIENT_FUNDS"
    svc.deposit(a, 100000, idem({"amount_minor": 100000}))  # now there is enough money
    again = transfer(svc, a, b, 10000, k=k)
    assert again.replayed and again.status == 422
    assert balance(svc, b) == 0
    assert transfer(svc, a, b, 10000).status == 201  # a new key works


def test_validation_errors_are_not_stored(svc, conn, funded):
    # FR-2.6: a 400 stores nothing, so the key can be used again.
    a, b = funded(50000), funded(0, name="Ravi")
    k = key()
    with pytest.raises(LedgerError) as err:
        svc.transfer(a, b, 10.5, IdempotencyRequest(k, "0" * 64))
    assert err.value.status == 400
    assert count(conn, "idempotency_keys") == 1  # only the setup deposit
    assert transfer(svc, a, b, 1000, k=k).status == 201


@pytest.mark.parametrize("bad_key,code", [
    (None, "IDEMPOTENCY_KEY_REQUIRED"), ("", "IDEMPOTENCY_KEY_REQUIRED"),
    ("short", "VALIDATION_ERROR"), ("has space!", "VALIDATION_ERROR"), ("x" * 129, "VALIDATION_ERROR"),
])
def test_idempotency_key_format(svc, funded, bad_key, code):
    a, b = funded(50000), funded(0, name="Ravi")
    with pytest.raises(LedgerError) as err:
        svc.transfer(a, b, 100, IdempotencyRequest(bad_key, "0" * 64))
    assert err.value.code == code and err.value.status == 400


def test_same_wallet_rejected(svc, funded):
    a = funded(50000)
    with pytest.raises(LedgerError) as err:
        transfer(svc, a, a, 100)
    assert err.value.code == "SAME_WALLET"


def test_unknown_wallet_is_404_stored(svc, funded):
    a = funded(50000)
    out = transfer(svc, a, str(uuid.uuid4()), 100)
    assert out.status == 404 and out.body["error"]["code"] == "WALLET_NOT_FOUND"


def test_cross_currency_rejected_until_fr6(svc, funded):
    inr, usd = funded(50000), funded(0, currency="USD", name="Sam")
    out = transfer(svc, inr, usd, 100)
    assert out.status == 422 and out.body["error"]["code"] == "CURRENCY_MISMATCH"
    assert balance(svc, inr) == 50000


def test_system_wallet_cannot_be_transfer_party(svc, conn, funded):
    a = funded(50000)
    system_id = conn.execute("SELECT id FROM wallets WHERE kind='SYSTEM' AND currency='INR'").fetchone()[0]
    out = transfer(svc, a, system_id, 100)
    assert out.status == 422 and out.body["error"]["code"] == "SYSTEM_WALLET_NOT_ALLOWED"


@pytest.mark.parametrize("amount", [0, -5, 100.0, "100", 100_000_001])
def test_bad_amounts_rejected(svc, funded, amount):
    a, b = funded(50000), funded(0, name="Ravi")
    with pytest.raises(LedgerError) as err:
        transfer(svc, a, b, amount)
    assert err.value.code == "VALIDATION_ERROR"


def test_exact_balance_can_be_spent(svc, funded):
    a, b = funded(10000), funded(0, name="Ravi")
    assert transfer(svc, a, b, 10000).status == 201
    assert balance(svc, a) == 0


# ================= FR-4: history, hash chain, reversals =================

def test_sequence_and_hash_chain(svc, conn, funded):
    a, b = funded(50000), funded(0, name="Ravi")
    transfer(svc, a, b, 100)
    transfer(svc, a, b, 200)
    rows = conn.execute("SELECT seq, prev_hash, hash FROM transactions ORDER BY seq").fetchall()
    assert [r["seq"] for r in rows] == [1, 2, 3]
    assert rows[0]["prev_hash"] == GENESIS_HASH
    for prev, cur in zip(rows, rows[1:]):
        assert cur["prev_hash"] == prev["hash"]


def test_reversal_mirrors_entries_and_keeps_original(svc, conn, funded, make_admin):
    admin = make_admin()
    a, b = funded(50000), funded(0, name="Ravi")
    original = transfer(svc, a, b, 10000).body["transaction"]["id"]
    out = svc.reverse(original, "wrong recipient", admin, idem({"reason": "wrong recipient"}))
    assert out.status == 201
    assert out.body["transaction"]["reverses_id"] == original
    assert [(e["wallet_id"], e["direction"]) for e in out.body["entries"]] == [(a, "CREDIT"), (b, "DEBIT")]
    assert balance(svc, a) == 50000 and balance(svc, b) == 0
    tx = svc.get_transaction(original)
    assert tx["reversed_by"] == out.body["transaction"]["id"] and len(tx["entries"]) == 2


def test_reverse_at_most_once(svc, funded, make_admin):
    admin = make_admin()
    a, b = funded(50000), funded(0, name="Ravi")
    original = transfer(svc, a, b, 100).body["transaction"]["id"]
    svc.reverse(original, "first", admin, idem({"r": 1}))
    again = svc.reverse(original, "second", admin, idem({"r": 2}))
    assert again.status == 409 and again.body["error"]["code"] == "ALREADY_REVERSED"


def test_cannot_reverse_a_reversal(svc, funded, make_admin):
    admin = make_admin()
    a, b = funded(50000), funded(0, name="Ravi")
    original = transfer(svc, a, b, 100).body["transaction"]["id"]
    reversal = svc.reverse(original, "oops", admin, idem({"r": 1})).body["transaction"]["id"]
    out = svc.reverse(reversal, "undo", admin, idem({"r": 2}))
    assert out.status == 422 and out.body["error"]["code"] == "CANNOT_REVERSE_REVERSAL"


def test_reversal_blocked_if_recipient_spent_it(svc, funded, make_admin):
    admin = make_admin()
    a, b, c = funded(50000), funded(0, name="Ravi"), funded(0, name="Mia")
    original = transfer(svc, a, b, 10000).body["transaction"]["id"]
    transfer(svc, b, c, 10000)
    out = svc.reverse(original, "late", admin, idem({"r": 1}))
    assert out.status == 422 and out.body["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert balance(svc, b) == 0


def test_reversal_needs_valid_reason_and_admin(svc, funded, make_admin, conn):
    admin = make_admin()
    a, b = funded(50000), funded(0, name="Ravi")
    original = transfer(svc, a, b, 100).body["transaction"]["id"]
    for reason in ("", "x" * 201, None):
        with pytest.raises(LedgerError) as err:
            svc.reverse(original, reason, admin, idem({"r": 1}))
        assert err.value.code == "VALIDATION_ERROR"
    conn.execute("UPDATE admin_keys SET revoked_at = '2026-11-27T00:00:00Z' WHERE id = ?", (admin,))
    with pytest.raises(LedgerError) as err:
        svc.reverse(original, "ok", admin, idem({"r": 1}))
    assert err.value.code == "UNAUTHORIZED"


def test_deposit_can_be_reversed(svc, funded, make_admin, conn):
    admin = make_admin()
    a = funded(50000)
    deposit_id = conn.execute("SELECT id FROM transactions WHERE type='DEPOSIT'").fetchone()[0]
    assert svc.reverse(deposit_id, "test deposit", admin, idem({"r": 1})).status == 201
    assert balance(svc, a) == 0 and system_balance(conn) == 0


def test_entries_paging(svc, funded):
    a, b = funded(100000), funded(0, name="Ravi")
    for i in range(5):
        transfer(svc, a, b, 100 + i)
    page1 = svc.list_entries(a, limit=3)
    assert len(page1["entries"]) == 3 and page1["next_after_id"] is not None
    page2 = svc.list_entries(a, limit=3, after_id=page1["next_after_id"])
    assert len(page2["entries"]) == 3  # a full page always offers next_after_id
    page3 = svc.list_entries(a, limit=3, after_id=page2["next_after_id"])
    assert page3 == {"wallet_id": a, "entries": [], "next_after_id": None}
    seqs = [e["seq"] for e in page1["entries"] + page2["entries"]]
    assert seqs == sorted(seqs) and len(seqs) == 6  # deposit + 5 transfers, in sequence order
    with pytest.raises(LedgerError):
        svc.list_entries(a, limit=501)
