"""Ledger reconciliation (SRS v1.1: FR-5.1 to FR-5.4).

reconcile(conn) reads one consistent snapshot, changes nothing, and returns
a report. A failed check is still a normal result: the API layer returns it
with 200 and status FAIL (FR-5.4). Admin authentication is done by the API
layer before calling this (FR-5.1, NFR-9).

Checks (FR-5.2)
  a  each transaction balances per currency
  b  the whole ledger balances per currency
  c  each stored wallet balance equals credits minus debits
  d  no user wallet is negative
  e  every transaction has two or more entries
  f  sequence numbers run 1..n with no gaps
  g  every hash recomputes and links to the previous hash (FR-4.4)
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Callable

from app.ledger.hashing import GENESIS_HASH, chain_hash
from app.ledger.repository import LedgerRepository
from app.ledger.service import utc_now

CHECKS = (
    ("a_transactions_balance", "Each transaction's debits equal its credits per currency"),
    ("b_ledger_balances", "Total debits equal total credits per currency"),
    ("c_wallet_balances_match", "Each stored balance equals credits minus debits"),
    ("d_no_negative_user_wallets", "No user wallet is negative"),
    ("e_two_or_more_entries", "Every transaction has two or more entries"),
    ("f_no_sequence_gaps", "Sequence numbers run from 1 with no gaps"),
    ("g_hash_chain_intact", "Every hash recomputes and links to the previous one"),
)


def reconcile(conn: sqlite3.Connection, clock: Callable[[], str] = utc_now) -> dict:
    repo = LedgerRepository(conn)
    repo.begin_read()  # one snapshot for every read below
    try:
        transactions = repo.all_transactions()
        entries = repo.all_entries()
        wallets = repo.all_wallets()
    finally:
        repo.rollback()  # read-only: nothing to keep (FR-5.1)

    found: dict[str, list] = {name: [] for name, _ in CHECKS}
    entries_by_tx: dict[str, list] = defaultdict(list)
    for e in entries:
        entries_by_tx[e["transaction_id"]].append(e)

    # (a) and (e): per transaction
    for tx in transactions:
        tx_entries = entries_by_tx.get(tx["id"], [])
        if len(tx_entries) < 2:
            found["e_two_or_more_entries"].append(
                {"transaction_id": tx["id"], "seq": tx["seq"], "expected": ">= 2", "actual": len(tx_entries)})
        net: dict[str, int] = defaultdict(int)
        for e in tx_entries:
            net[e["currency"]] += e["amount_minor"] if e["direction"] == "CREDIT" else -e["amount_minor"]
        for currency, value in sorted(net.items()):
            if value != 0:
                found["a_transactions_balance"].append(
                    {"transaction_id": tx["id"], "seq": tx["seq"], "currency": currency,
                     "expected": 0, "actual": value})

    # (b): whole ledger per currency
    totals: dict[str, dict] = defaultdict(lambda: {"debits_minor": 0, "credits_minor": 0})
    for e in entries:
        key = "credits_minor" if e["direction"] == "CREDIT" else "debits_minor"
        totals[e["currency"]][key] += e["amount_minor"]
    for currency, t in sorted(totals.items()):
        if t["debits_minor"] != t["credits_minor"]:
            found["b_ledger_balances"].append(
                {"currency": currency, "expected": t["debits_minor"], "actual": t["credits_minor"]})

    # (c) and (d): per wallet
    net_by_wallet: dict[str, int] = defaultdict(int)
    for e in entries:
        net_by_wallet[e["wallet_id"]] += e["amount_minor"] if e["direction"] == "CREDIT" else -e["amount_minor"]
    for w in wallets:
        expected = net_by_wallet.get(w["id"], 0)
        if w["balance_minor"] != expected:
            found["c_wallet_balances_match"].append(
                {"wallet_id": w["id"], "expected": expected, "actual": w["balance_minor"]})
        if w["kind"] == "USER" and w["balance_minor"] < 0:
            found["d_no_negative_user_wallets"].append(
                {"wallet_id": w["id"], "expected": ">= 0", "actual": w["balance_minor"]})

    # (f): sequence numbers 1..n
    for position, tx in enumerate(transactions, start=1):
        if tx["seq"] != position:
            found["f_no_sequence_gaps"].append(
                {"transaction_id": tx["id"], "expected": position, "actual": tx["seq"]})
            break  # the first gap is enough to locate the problem

    # (g): hash chain
    prev = GENESIS_HASH
    for tx in transactions:
        recomputed = chain_hash(tx["prev_hash"], dict(tx), [dict(e) for e in entries_by_tx.get(tx["id"], [])])
        if tx["prev_hash"] != prev or tx["hash"] != recomputed:
            found["g_hash_chain_intact"].append({
                "transaction_id": tx["id"], "seq": tx["seq"],
                "expected": recomputed if tx["prev_hash"] == prev else f"prev_hash {prev}",
                "actual": tx["hash"] if tx["prev_hash"] == prev else f"prev_hash {tx['prev_hash']}",
                "note": "first transaction whose hash does not match",
            })
            break  # everything after the first break is suspect anyway
        prev = tx["hash"]

    checks = {name: {"description": desc, "passed": not found[name], "discrepancies": found[name]}
              for name, desc in CHECKS}
    latest = transactions[-1] if transactions else None
    return {
        "status": "PASS" if all(c["passed"] for c in checks.values()) else "FAIL",
        "checks": checks,
        "totals": {c: dict(t) for c, t in sorted(totals.items())},
        "transactions_checked": len(transactions),
        "latest_seq": latest["seq"] if latest else 0,
        "latest_hash": latest["hash"] if latest else GENESIS_HASH,
        "checked_at": clock(),
    }
