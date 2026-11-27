"""Hash chain and request fingerprints (SRS v1.1: FR-2.2, FR-4.4, FR-4.5).

Hash chain
    hash = SHA-256(prev_hash ∥ canonical JSON), hex-encoded.
    The first transaction uses 64 zeros as prev_hash.

Canonical JSON (FR-4.5, plus ADR 0002 for the entry fields)
    The transaction's id, seq, type, reverses_id, fx_rate_id, admin_id,
    reason and created_at, and its entries in posting (id) order. Each entry
    contributes wallet_id, direction, amount_minor and balance_after.
    Keys are sorted, there is no whitespace, and the text is UTF-8.
    The entry's own id is left out: it is assigned by SQLite after the hash
    has to be known, and posting order already fixes the entry order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

GENESIS_HASH = "0" * 64

TRANSACTION_HASH_FIELDS = (
    "id", "seq", "type", "reverses_id", "fx_rate_id", "admin_id", "reason", "created_at",
)
ENTRY_HASH_FIELDS = ("wallet_id", "direction", "amount_minor", "balance_after")


def canonical_json(value: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8 (non-ASCII kept as-is)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def transaction_payload(transaction: Mapping[str, Any], entries: Iterable[Mapping[str, Any]]) -> dict:
    """The exact dict that is hashed for one transaction."""
    payload = {field: transaction.get(field) for field in TRANSACTION_HASH_FIELDS}
    payload["entries"] = [{field: entry[field] for field in ENTRY_HASH_FIELDS} for entry in entries]
    return payload


def chain_hash(prev_hash: str, transaction: Mapping[str, Any], entries: Iterable[Mapping[str, Any]]) -> str:
    """hash = SHA-256(prev_hash ∥ canonical JSON) as 64 hex characters (FR-4.4)."""
    if len(prev_hash) != 64:
        raise ValueError("prev_hash must be 64 hex characters")
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("ascii"))
    digest.update(canonical_json(transaction_payload(transaction, entries)))
    return digest.hexdigest()


def request_fingerprint(method: str, path: str, body: Any) -> str:
    """SHA-256 of method, path and body as sorted-key JSON (FR-2.2).

    Two requests with the same key are "the same request" only when this
    fingerprint matches (FR-2.4); otherwise the key was reused (FR-2.5).
    """
    digest = hashlib.sha256()
    digest.update(method.upper().encode("ascii"))
    digest.update(b"\n")
    digest.update(path.encode("utf-8"))
    digest.update(b"\n")
    digest.update(canonical_json(body))
    return digest.hexdigest()
