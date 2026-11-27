---
name: simulate-transfer
description: Run an end-to-end check of the running Financial Ledger API — fund a wallet, transfer and retry with the same idempotency key, race two transfers that overspend, and reconcile. Use before a demo, after a merge that touches money logic, or when asked to "simulate a transfer" or "check the ledger end to end".
---

# simulate-transfer

Runs the SK-6 workflow from SRS v1.1 against a **running** server and reports PASS or FAIL. It proves, through the real HTTP API, the guarantees in [[double-entry-ledger]] and [[sqlite-transactions-and-locking]]: retries never move money twice (FR-2), concurrent transfers never overspend (FR-3), and the ledger reconciles (FR-5).

## Before you start
1. Start the server locally (see README).
2. Create an administrator key with the key tool (NFR-9a) and put it in the environment as `LEDGER_ADMIN_KEY`. Never paste the key into the chat, a note, or a commit.

## Steps
1. Run:
   ```bash
   python skills/simulate-transfer/scripts/simulate_transfer.py --base-url http://127.0.0.1:8000
   ```
2. The script does, in order:
   1. creates two accounts with INR wallets and deposits 50000 (₹500.00) into the first;
   2. records both balances (expect 50000 and 0);
   3. transfers 10000 with an `Idempotency-Key`, then sends the same request with the same key: the second answer must be identical and carry `Idempotent-Replayed: true`, and balances must be 40000 and 10000;
   4. sends two transfers of 30000 at the same moment (60000 > 40000 left): exactly one returns 201, the other 422 `INSUFFICIENT_FUNDS`, and balances must be 10000 and 40000;
   5. calls `GET /admin/reconciliation` with the admin key: status must be `PASS`.
3. Read the JSON report it prints. Exit code 0 = PASS, 1 = FAIL.
4. Summarise for the user: the result, the final balances in rupees, and for a FAIL, the failing step and its details.

## Rules
- Fails on any of: reconciliation `FAIL`, both racing transfers succeeding, any balance not as expected, any unexpected status.
- Never print, log or repeat `LEDGER_ADMIN_KEY` (C-6, NFR-10). The script redacts it from its own output.
- Only use a local or test server. The wallets it creates stay in the database (BR-7), so do not run it against data you need to keep clean.

## Evaluation
See `evals/evals.md` (SK-8, TQ-7). The automated harness is `tests/test_simulate_transfer_skill.py`.
