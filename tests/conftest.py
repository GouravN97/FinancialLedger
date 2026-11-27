"""Shared fixtures. Every test gets a new temporary database file (NFR-7, TQ-5)."""

import hashlib
import itertools
import uuid

import pytest

from app.db.connection import init_db
from app.ledger.hashing import request_fingerprint
from app.ledger.service import IdempotencyRequest, LedgerService

_counter = itertools.count(1)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ledger.db"
    init_db(path).close()
    return path


@pytest.fixture
def conn(db_path):
    from app.db.connection import connect
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def svc(conn):
    return LedgerService(conn)


def key(prefix="key"):
    """A fresh, valid Idempotency-Key."""
    return f"{prefix}-{next(_counter):06d}-{uuid.uuid4().hex[:8]}"


def idem(body, path="/transfers", k=None):
    return IdempotencyRequest(k or key(), request_fingerprint("POST", path, body))


@pytest.fixture
def make_admin(conn):
    def _make(name="admin"):
        admin_id = str(uuid.uuid4())
        key_hash = hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()
        conn.execute("INSERT INTO admin_keys (id, name, key_hash) VALUES (?, ?, ?)", (admin_id, name, key_hash))
        return admin_id
    return _make


@pytest.fixture
def funded(svc):
    """Make a user wallet holding `amount` minor units."""
    def _funded(amount=50000, currency="INR", name="Asha"):
        account = svc.create_account(name)
        wallet = svc.create_wallet(account["id"], currency)
        if amount:
            body = {"amount_minor": amount}
            out = svc.deposit(wallet["id"], amount, idem(body, f"/wallets/{wallet['id']}/deposits"))
            assert out.status == 201
        return wallet["id"]
    return _funded
