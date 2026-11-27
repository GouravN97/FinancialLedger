# ADR 0002: Ledger schema, posting model and hash-chain content

- Status: Accepted
- Date: 2026-11-27
- Author: Vishudha Sood (Ledger owner)
- Requirements: DB-1 to DB-4, FR-1.3, FR-3.1, FR-3.5, FR-4.1, FR-4.4, FR-4.5, FR-5.2, BR-1, BR-2, BR-7, BR-8
- Research: [[double-entry-ledger]], [[sqlite-transactions-and-locking]], [[hash-chains]]

## Context
The SRS fixes seven tables (Figure 2) and the rules they must enforce. Two points were left open: how a posting is written so it is atomic, and which entry fields go into the hash (FR-4.5 says "its entries in id order" but does not list their fields).

## Decision

### Tables (migration `app/db/migrations/001_init.sql`)
| Table | Purpose | Key constraints |
|---|---|---|
| `accounts` | A user | name 1–100 chars; no DELETE (BR-7) |
| `wallets` | Balance in one currency; kind USER, SYSTEM or FX_CLEARING | one per account per currency; only USER has an account; USER balance ≥ 0 (FR-3.5, BR-2); one SYSTEM and one FX_CLEARING per currency (partial unique index); no DELETE |
| `transactions` | One money movement | `seq` unique; `reverses_id` UNIQUE (reverse once, BR-8); a REVERSAL needs admin_id and reason; no UPDATE/DELETE |
| `ledger_entries` | Debit/credit lines | amount > 0 and integer; no UPDATE/DELETE |
| `idempotency_keys` | Stored responses | key 8–128 chars; no UPDATE/DELETE |
| `fx_rates` | Rate history (FR-6) | integer rate_scaled 1–10¹²; no UPDATE/DELETE |
| `admin_keys` | Per-admin key hashes | UPDATE allowed only so `revoked_at` can be set |

`wallets.balance_minor` is a cached value. Reconciliation check (c) proves it equals credits minus debits.

### Posting model (`LedgerService._post`)
Inside one `BEGIN IMMEDIATE`:
1. Check debits = credits per currency (programming error otherwise).
2. Compute every new balance and reject with `INSUFFICIENT_FUNDS` if a USER wallet would go negative. Nothing has been written yet.
3. `seq` = last seq + 1 (1 for the first); `prev_hash` = last hash (64 zeros for the first).
4. Compute the hash, insert the transaction, insert entries in leg order, update balances.

### Hash content (fills the FR-4.5 gap)
`hash = SHA-256(prev_hash ∥ canonical_json(payload))`, where `payload` is:
- the transaction's `id, seq, type, reverses_id, fx_rate_id, admin_id, reason, created_at`;
- `entries`: a list, in posting order (= ascending entry id), of `{wallet_id, direction, amount_minor, balance_after}`.

Canonical JSON = sorted keys, separators `,` and `:` with no spaces, UTF-8, non-ASCII kept as-is. The entry `id` is **not** hashed, because SQLite assigns it only after the hash must be known; posting order already fixes the order.

## Consequences
- A direct edit of any hashed field, or of the entry order, breaks check (g) at that transaction (tested in `tests/test_reconciliation.py`).
- `balance_after` is hashed, so rewriting history to hide a balance change is also caught.
- Fields outside the payload (`created_at` of entries, the wallet's cached balance) are covered by other checks, not the hash.
- Writes are strictly serial, which the SRS already accepts (T-1, T-4).

## Alternatives considered
- Hash per entry instead of per transaction: more rows to chain, and a transaction's entries could be reordered between chains. Rejected.
- Leave entry fields unspecified: two implementations could disagree, making TQ-10 unreliable. Rejected.
