"""Unit tests: money utility, hashing, fingerprints (TQ-1, TQ-6)."""

import pytest

from app.errors import LedgerError
from app.ledger.hashing import (GENESIS_HASH, canonical_json, chain_hash, request_fingerprint,
                                transaction_payload)
from app.money import format_minor, parse_amount, parse_currency


# ---------- money (C-3, NFR-8, BR-4, FR-2.7) ----------

@pytest.mark.parametrize("value", [1, 10050, 100_000_000])
def test_parse_amount_accepts_whole_minor_units(value):
    assert parse_amount(value) == value


@pytest.mark.parametrize("value", [0, -1, 100_000_001])
def test_parse_amount_rejects_out_of_range(value):
    with pytest.raises(LedgerError) as err:
        parse_amount(value)
    assert err.value.code == "VALIDATION_ERROR" and err.value.status == 400


@pytest.mark.parametrize("value", [100.0, 100.5, "100", None, True, False, [100]])
def test_parse_amount_rejects_anything_but_int(value):
    # 100.0 is what JSON decoding gives for "100.0"; "100" is a string. Both are refused (TQ-6).
    with pytest.raises(LedgerError) as err:
        parse_amount(value)
    assert err.value.code == "VALIDATION_ERROR"


def test_parse_currency():
    assert parse_currency("USD") == "USD"
    for bad in ("GBP", "inr", 1, None):
        with pytest.raises(LedgerError):
            parse_currency(bad)


@pytest.mark.parametrize("amount,currency,text", [
    (10050, "INR", "₹100.50"), (5, "USD", "$0.05"), (-50000, "INR", "-₹500.00"), (123456789, "EUR", "€1,234,567.89"),
])
def test_format_minor(amount, currency, text):
    assert format_minor(amount, currency) == text


def test_format_minor_refuses_floats():
    with pytest.raises(TypeError):
        format_minor(100.5, "INR")


# ---------- canonical JSON and hash chain (FR-4.4, FR-4.5) ----------

TX = {"id": "t1", "seq": 1, "type": "DEPOSIT", "reverses_id": None, "fx_rate_id": None,
      "admin_id": None, "reason": None, "created_at": "2026-11-27T00:00:00.000Z"}
ENTRIES = [
    {"wallet_id": "sys", "direction": "DEBIT", "amount_minor": 500, "balance_after": -500},
    {"wallet_id": "w1", "direction": "CREDIT", "amount_minor": 500, "balance_after": 500},
]


def test_canonical_json_is_sorted_and_compact():
    assert canonical_json({"b": 1, "a": "₹"}) == '{"a":"₹","b":1}'.encode("utf-8")


def test_payload_uses_only_the_listed_fields():
    tx = dict(TX, hash="ignored", prev_hash="ignored", extra="ignored")
    entries = [dict(e, id=99, transaction_id="t1") for e in ENTRIES]
    payload = transaction_payload(tx, entries)
    assert set(payload) == {"id", "seq", "type", "reverses_id", "fx_rate_id", "admin_id", "reason",
                            "created_at", "entries"}
    assert payload["entries"][0] == ENTRIES[0]


def test_chain_hash_is_deterministic_and_64_hex():
    h = chain_hash(GENESIS_HASH, TX, ENTRIES)
    assert h == chain_hash(GENESIS_HASH, TX, ENTRIES)
    assert len(h) == 64 and int(h, 16) >= 0


def test_chain_hash_changes_when_anything_changes():
    base = chain_hash(GENESIS_HASH, TX, ENTRIES)
    edited_amount = [ENTRIES[0], dict(ENTRIES[1], amount_minor=501)]
    assert chain_hash(GENESIS_HASH, TX, edited_amount) != base
    assert chain_hash(GENESIS_HASH, dict(TX, seq=2), ENTRIES) != base
    assert chain_hash("1" * 64, TX, ENTRIES) != base            # linked to the previous hash
    assert chain_hash(GENESIS_HASH, TX, ENTRIES[::-1]) != base  # entry order matters


# ---------- request fingerprint (FR-2.2) ----------

def test_fingerprint_ignores_key_order_only():
    a = request_fingerprint("POST", "/transfers", {"amount_minor": 1, "source_wallet_id": "x"})
    b = request_fingerprint("post", "/transfers", {"source_wallet_id": "x", "amount_minor": 1})
    assert a == b and len(a) == 64
    assert request_fingerprint("POST", "/transfers", {"amount_minor": 2, "source_wallet_id": "x"}) != a
    assert request_fingerprint("POST", "/other", {"amount_minor": 1, "source_wallet_id": "x"}) != a
