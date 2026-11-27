# simulate-transfer evaluation cases (SK-8, TQ-7)

Cases 1 to 4 are automated in `tests/test_simulate_transfer_skill.py`, which runs the script against a small test server built on `LedgerService`. Run case 5 by hand against the real FastAPI server before each stage.

| # | Setup | Expected result |
|---|---|---|
| 1 | Healthy ledger, correct admin key | Exit 0, `result: PASS`, final balances sender 10000, receiver 40000 |
| 2 | Server that lets both racing transfers succeed (broken race safety) | Exit 1, failing step "race: exactly one of two succeeds" |
| 3 | Wrong admin key | Exit 1, failing step "reconciliation passes" with `HTTP 401`; the key is not in the output |
| 4 | No server listening | Exit 1, problem "cannot reach …" |
| 5 | Real FastAPI server after the API PR is merged | Same as case 1 |

## Results

| Date | Case | Pass/Fail | Notes | Run by |
|---|---|---|---|---|
| 2026-11-28 | 1–4 | Pass | Automated harness, before the FastAPI routes exist | VishudhaSood (with Claude) |
| | 5 | | Run after the API PR is merged | |
