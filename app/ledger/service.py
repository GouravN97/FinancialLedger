"""Ledger service layer: all money rules live here (NFR-16).

What this module gives the API layer
------------------------------------
    svc = LedgerService(conn)

    svc.create_account(name)                          -> dict          FR-1.1
    svc.create_wallet(account_id, currency)           -> dict          FR-1.2
    svc.get_wallet(wallet_id)                         -> dict          FR-1.5
    svc.list_entries(wallet_id, limit, after_id)      -> dict          FR-4.6
    svc.get_transaction(transaction_id)               -> dict          FR-4.7

    svc.deposit(wallet_id, amount_minor, idem)        -> Outcome       FR-1.4
    svc.transfer(source_id, dest_id, amount, idem)    -> Outcome       FR-2, FR-3
    svc.reverse(transaction_id, reason, admin_id, idem) -> Outcome     FR-4.2, FR-4.3

`idem` is IdempotencyRequest(key, fingerprint). Build the fingerprint with
app.ledger.hashing.request_fingerprint(method, path, body) (FR-2.2).

How the API layer uses the result
---------------------------------
* An Outcome is the final answer: send Outcome.body with Outcome.status and,
  if Outcome.replayed, the header "Idempotent-Replayed: true" (Section 3.4).
  Stored business rejections (404, 409 ALREADY_REVERSED, 422) also come back
  as an Outcome, because they are stored with the key (FR-2.3).
* A raised LedgerError was not stored (400, 409 IDEMPOTENCY_KEY_REUSED, 503,
  FR-2.6): send err.body() with err.status.
* Admin authentication (NFR-9) happens in the API layer before reverse() is
  called, so it always precedes the idempotency lookup. reverse() receives
  the authenticated admin_keys.id.

One money operation = one database transaction
----------------------------------------------
Each keyed call runs inside a single BEGIN IMMEDIATE (FR-3.1): idempotency
lookup, business checks, entries, balance updates, hash-chain update and the
idempotency record. Any unexpected failure rolls all of it back (FR-3.2).
If the write lock is not free within the busy timeout, the call raises
SERVICE_BUSY with nothing written (FR-3.3).
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from app.errors import LedgerError
from app.ledger.hashing import GENESIS_HASH, chain_hash
from app.ledger.repository import LedgerRepository
from app.money import parse_amount, parse_currency

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")  # Section 3.4
DEFAULT_PAGE_SIZE = 50                                     # FR-4.6
MAX_PAGE_SIZE = 500


@dataclass(frozen=True)
class IdempotencyRequest:
    key: Optional[str]
    fingerprint: str


@dataclass(frozen=True)
class Outcome:
    status: int
    body: dict
    replayed: bool = False


def utc_now() -> str:
    """UTC ISO 8601 with milliseconds, e.g. 2026-11-27T10:15:00.123Z (DB-4)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_uuid(value: object, field: str) -> str:
    """Return value if it is a UUID string, else 400 VALIDATION_ERROR (FR-1.6)."""
    if not isinstance(value, str):
        raise LedgerError("VALIDATION_ERROR", f"{field} must be a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise LedgerError("VALIDATION_ERROR", f"{field} must be a UUID") from None


def _is_lock_error(err: sqlite3.OperationalError) -> bool:
    text = str(err).lower()
    return "locked" in text or "busy" in text


class LedgerService:
    def __init__(self, conn: sqlite3.Connection,
                 clock: Callable[[], str] = utc_now,
                 new_id: Callable[[], str] = lambda: str(uuid.uuid4())):
        self.repo = LedgerRepository(conn)
        self.clock = clock
        self.new_id = new_id

    # =================================================================
    # Accounts and wallets (FR-1.1, FR-1.2)
    # =================================================================

    def create_account(self, name: object) -> dict:
        if not isinstance(name, str) or not 1 <= len(name) <= 100:
            raise LedgerError("VALIDATION_ERROR", "name must be 1 to 100 characters")
        account = {"id": self.new_id(), "name": name, "created_at": self.clock()}
        self._write(lambda: self.repo.insert_account(account["id"], name, account["created_at"]))
        return account

    def create_wallet(self, account_id: object, currency: object) -> dict:
        account_id = parse_uuid(account_id, "account_id")
        currency = parse_currency(currency)
        wallet = {"id": self.new_id(), "account_id": account_id, "currency": currency,
                  "balance_minor": 0, "created_at": self.clock()}

        def work():
            if self.repo.get_account(account_id) is None:
                raise LedgerError("ACCOUNT_NOT_FOUND", f"account {account_id} does not exist")
            if self.repo.find_user_wallet(account_id, currency) is not None:
                raise LedgerError("WALLET_EXISTS", f"account already has a {currency} wallet")
            self.repo.insert_wallet(wallet["id"], account_id, currency, wallet["created_at"])

        self._write(work)
        return wallet

    # =================================================================
    # Reads (FR-1.5, FR-4.6, FR-4.7)
    # =================================================================

    def get_wallet(self, wallet_id: object) -> dict:
        wallet_id = parse_uuid(wallet_id, "wallet_id")
        row = self.repo.get_wallet(wallet_id)
        if row is None:
            raise LedgerError("WALLET_NOT_FOUND", f"wallet {wallet_id} does not exist")
        return _wallet_dict(row)

    def list_entries(self, wallet_id: object, limit: object = DEFAULT_PAGE_SIZE,
                     after_id: object = None) -> dict:
        wallet_id = parse_uuid(wallet_id, "wallet_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
            raise LedgerError("VALIDATION_ERROR", f"limit must be 1 to {MAX_PAGE_SIZE}")
        if after_id is not None and (isinstance(after_id, bool) or not isinstance(after_id, int) or after_id < 0):
            raise LedgerError("VALIDATION_ERROR", "after_id must be a non-negative integer")
        if self.repo.get_wallet(wallet_id) is None:
            raise LedgerError("WALLET_NOT_FOUND", f"wallet {wallet_id} does not exist")
        rows = self.repo.wallet_entries(wallet_id, after_id, limit)
        entries = [{
            "id": r["id"], "transaction_id": r["transaction_id"], "seq": r["seq"], "type": r["type"],
            "direction": r["direction"], "amount_minor": r["amount_minor"],
            "balance_after": r["balance_after"], "created_at": r["created_at"],
        } for r in rows]
        next_after_id = entries[-1]["id"] if len(entries) == limit else None
        return {"wallet_id": wallet_id, "entries": entries, "next_after_id": next_after_id}

    def get_transaction(self, transaction_id: object) -> dict:
        transaction_id = parse_uuid(transaction_id, "transaction_id")
        tx = self.repo.get_transaction(transaction_id)
        if tx is None:
            raise LedgerError("TRANSACTION_NOT_FOUND", f"transaction {transaction_id} does not exist")
        reversal = self.repo.find_reversal_of(transaction_id)
        body = _transaction_dict(tx)
        body["entries"] = [_entry_dict(e) for e in self.repo.entries_of(transaction_id)]
        body["reversed_by"] = reversal["id"] if reversal else None
        return body

    # =================================================================
    # Money movements (keyed, idempotent)
    # =================================================================

    def deposit(self, wallet_id: object, amount_minor: object, idem: IdempotencyRequest) -> Outcome:
        """FR-1.4: debit the currency's SYSTEM wallet, credit the user wallet."""
        wallet_id = parse_uuid(wallet_id, "wallet_id")
        amount = parse_amount(amount_minor)

        def work():
            wallet = self._user_wallet(wallet_id)
            system = self.repo.get_internal_wallet("SYSTEM", wallet["currency"])
            return self._post("DEPOSIT", [(system, "DEBIT", amount), (wallet, "CREDIT", amount)])

        return self._keyed(idem, work)

    def transfer(self, source_wallet_id: object, destination_wallet_id: object,
                 amount_minor: object, idem: IdempotencyRequest) -> Outcome:
        """FR-2.8, FR-2.9, FR-2.10: same-currency transfer between user wallets."""
        source_id = parse_uuid(source_wallet_id, "source_wallet_id")
        dest_id = parse_uuid(destination_wallet_id, "destination_wallet_id")
        amount = parse_amount(amount_minor)
        if source_id == dest_id:
            raise LedgerError("SAME_WALLET", "source and destination must be different wallets")

        def work():
            source = self._user_wallet(source_id)
            dest = self._user_wallet(dest_id)
            if source["currency"] != dest["currency"]:
                # FR-2.10: until FR-6 is implemented
                raise LedgerError(
                    "CURRENCY_MISMATCH",
                    f"cannot transfer {source['currency']} to a {dest['currency']} wallet",
                )
            return self._post("TRANSFER", [(source, "DEBIT", amount), (dest, "CREDIT", amount)])

        return self._keyed(idem, work)

    def reverse(self, transaction_id: object, reason: object, admin_id: str,
                idem: IdempotencyRequest) -> Outcome:
        """FR-4.2, FR-4.3: mirror every entry of the original, once."""
        transaction_id = parse_uuid(transaction_id, "transaction_id")
        if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
            raise LedgerError("VALIDATION_ERROR", "reason must be 1 to 200 characters")
        if not isinstance(admin_id, str) or not admin_id:
            raise LedgerError("UNAUTHORIZED", "an authenticated administrator is required")

        def work():
            original = self.repo.get_transaction(transaction_id)
            if original is None:
                raise LedgerError("TRANSACTION_NOT_FOUND", f"transaction {transaction_id} does not exist")
            if original["type"] == "REVERSAL":
                raise LedgerError("CANNOT_REVERSE_REVERSAL", "a reversal cannot be reversed")
            if self.repo.find_reversal_of(transaction_id) is not None:
                raise LedgerError("ALREADY_REVERSED", "this transaction has already been reversed")
            if not self.repo.admin_exists(admin_id):
                raise LedgerError("UNAUTHORIZED", "administrator key is missing, wrong or revoked")
            legs = []
            for entry in self.repo.entries_of(transaction_id):
                wallet = self.repo.get_wallet(entry["wallet_id"])
                opposite = "CREDIT" if entry["direction"] == "DEBIT" else "DEBIT"
                legs.append((wallet, opposite, entry["amount_minor"]))
            return self._post("REVERSAL", legs, reverses_id=transaction_id,
                              admin_id=admin_id, reason=reason)

        return self._keyed(idem, work)

    # =================================================================
    # Internals
    # =================================================================

    def _user_wallet(self, wallet_id: str) -> sqlite3.Row:
        wallet = self.repo.get_wallet(wallet_id)
        if wallet is None:
            raise LedgerError("WALLET_NOT_FOUND", f"wallet {wallet_id} does not exist")
        if wallet["kind"] != "USER":
            raise LedgerError("SYSTEM_WALLET_NOT_ALLOWED", "system and FX clearing wallets cannot be used here")
        return wallet

    def _post(self, tx_type: str, legs: list, reverses_id: Optional[str] = None,
              admin_id: Optional[str] = None, reason: Optional[str] = None) -> tuple:
        """Write one balanced transaction. Must run inside an open BEGIN IMMEDIATE.

        All checks happen before the first write, so a rejection writes nothing.
        Returns (status, body, transaction_id).
        """
        # BR-1: debits equal credits within each currency.
        totals: dict[str, int] = {}
        for wallet, direction, amount in legs:
            sign = 1 if direction == "CREDIT" else -1
            totals[wallet["currency"]] = totals.get(wallet["currency"], 0) + sign * amount
        if any(totals.values()) or len(legs) < 2:
            raise RuntimeError(f"unbalanced posting {totals}")  # programming error, never a user error

        # New balances, checked before anything is written (FR-2.8, FR-4.3).
        balances = {w["id"]: w["balance_minor"] for w, _, _ in legs}
        entries = []
        for wallet, direction, amount in legs:
            balances[wallet["id"]] += amount if direction == "CREDIT" else -amount
            entries.append({"wallet_id": wallet["id"], "direction": direction,
                            "amount_minor": amount, "balance_after": balances[wallet["id"]]})
        for wallet, _, _ in legs:
            if wallet["kind"] == "USER" and balances[wallet["id"]] < 0:  # BR-2
                raise LedgerError("INSUFFICIENT_FUNDS", f"wallet {wallet['id']} has insufficient funds")

        # Sequence number and hash chain (FR-4.4, FR-4.5).
        last = self.repo.last_transaction()
        tx = {
            "id": self.new_id(),
            "seq": (last["seq"] + 1) if last else 1,
            "type": tx_type,
            "reverses_id": reverses_id,
            "fx_rate_id": None,
            "admin_id": admin_id,
            "reason": reason,
            "created_at": self.clock(),
            "prev_hash": last["hash"] if last else GENESIS_HASH,
        }
        tx["hash"] = chain_hash(tx["prev_hash"], tx, entries)

        self.repo.insert_transaction(tx)
        for entry in entries:
            entry["id"] = self.repo.insert_entry(tx["id"], entry)
        for wallet_id, balance in balances.items():
            self.repo.set_balance(wallet_id, balance)

        user_balances = {w["id"]: balances[w["id"]] for w, _, _ in legs if w["kind"] == "USER"}
        body = {
            "transaction": {k: tx[k] for k in ("id", "seq", "type", "reverses_id", "admin_id",
                                               "reason", "created_at", "hash")},
            "entries": [{k: e[k] for k in ("id", "wallet_id", "direction", "amount_minor", "balance_after")}
                        for e in entries],
            "balances": user_balances,
        }
        return 201, body, tx["id"]

    def _begin_immediate(self) -> None:
        try:
            self.repo.begin_immediate()
        except sqlite3.OperationalError as err:
            if _is_lock_error(err):
                raise LedgerError("SERVICE_BUSY", "the ledger is busy; retry with the same key") from None
            raise

    def _write(self, work: Callable[[], None]) -> None:
        """Run a non-money write in its own BEGIN IMMEDIATE."""
        self._begin_immediate()
        try:
            work()
            self.repo.commit()
        except BaseException:
            self.repo.rollback()
            raise

    def _keyed(self, idem: IdempotencyRequest, work: Callable[[], tuple]) -> Outcome:
        """Idempotency + one database transaction around a money operation."""
        if idem is None or idem.key is None or idem.key == "":
            raise LedgerError("IDEMPOTENCY_KEY_REQUIRED", "the Idempotency-Key header is required")
        if not isinstance(idem.key, str) or not IDEMPOTENCY_KEY_RE.match(idem.key):
            raise LedgerError("VALIDATION_ERROR",
                              "Idempotency-Key must be 8 to 128 letters, digits, '-' or '_'")
        if not isinstance(idem.fingerprint, str) or len(idem.fingerprint) != 64:
            raise ValueError("fingerprint must be a 64-character SHA-256 hex digest")

        self._begin_immediate()
        try:
            stored = self.repo.get_idempotency(idem.key)  # FR-2.4: lookup inside the transaction
            if stored is not None:
                self.repo.rollback()
                if stored["fingerprint"] != idem.fingerprint:
                    raise LedgerError("IDEMPOTENCY_KEY_REUSED",
                                      "this Idempotency-Key was already used for a different request")
                return Outcome(stored["status_code"], json.loads(stored["response_body"]), replayed=True)

            self.repo.savepoint("op")
            try:
                status, body, transaction_id = work()
            except LedgerError as err:
                if not err.stored_with_key:
                    raise
                # FR-2.3: business rejections are stored with the key.
                self.repo.rollback_to("op")
                status, body, transaction_id = err.status, err.body(), None
            self.repo.release("op")

            self.repo.insert_idempotency(idem.key, idem.fingerprint, status,
                                         json.dumps(body, sort_keys=True, ensure_ascii=False),
                                         transaction_id, self.clock())
            self.repo.commit()
            return Outcome(status, body)
        except BaseException:
            self.repo.rollback()
            raise


def _wallet_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("id", "account_id", "currency", "kind", "balance_minor", "created_at")}


def _transaction_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("id", "seq", "type", "reverses_id", "fx_rate_id", "admin_id",
                                "reason", "prev_hash", "hash", "created_at")}


def _entry_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("id", "wallet_id", "direction", "amount_minor", "balance_after")}
