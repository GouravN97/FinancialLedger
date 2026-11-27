# Ledger core: design and API contract

Owner: Vishudha Sood (Ledger owner). Date: 2026-11-27. Branch: `ledger/core`.

This is what the API owner and Quality owner build on. The ledger core is the service and repository layers for FR-1 to FR-5. It has no HTTP code: the FastAPI endpoints call it.

## Components

```mermaid
flowchart TB
  API["API layer (FastAPI routes)<br/>validates headers, admin auth, maps errors"] --> SVC
  subgraph core["Ledger core (this branch)"]
    SVC["app/ledger/service.py<br/>LedgerService: money rules, idempotency"]
    REC["app/ledger/reconciliation.py<br/>reconcile()"]
    HASH["app/ledger/hashing.py<br/>hash chain, request fingerprint"]
    MONEY["app/money.py<br/>integer money"]
    ERR["app/errors.py<br/>LedgerError + SRS error codes"]
    REPO["app/ledger/repository.py<br/>all SQL"]
    DB["app/db/connection.py<br/>connect(), init_db(), migrations"]
    SVC --> HASH & MONEY & ERR & REPO
    REC --> HASH & REPO
  end
  API --> REC
  REPO --> SQL[("SQLite file<br/>001_init.sql")]
  DB --> SQL
```

Layer rules (NFR-16): only `repository.py` and `connection.py` contain SQL; only `service.py` and `reconciliation.py` contain money rules.

## Transfer sequence (POST /transfers)

One request, start to finish. Everything between `BEGIN IMMEDIATE` and `COMMIT` is one database transaction (FR-3.1), so it is written completely or not at all.

```mermaid
sequenceDiagram
    autonumber
    actor C as Client
    participant A as API layer
    participant S as LedgerService
    participant R as LedgerRepository
    participant D as SQLite file

    C->>A: POST /transfers + Idempotency-Key + JSON body
    A->>A: request_fingerprint(method, path, body)
    A->>S: transfer(source, destination, amount, idem)
    S->>S: parse_uuid, parse_amount, same wallet? (400s, nothing stored)
    S->>R: begin_immediate()
    R->>D: BEGIN IMMEDIATE (waits up to 5 s for the write lock)
    alt lock not obtained
        D-->>S: database is locked
        S-->>A: LedgerError SERVICE_BUSY (503)
    else lock held
        S->>R: get_idempotency(key)
        alt key seen, same fingerprint
            S->>R: rollback()
            S-->>A: Outcome(stored status, stored body, replayed=True)
        else key seen, different fingerprint
            S->>R: rollback()
            S-->>A: LedgerError IDEMPOTENCY_KEY_REUSED (409)
        else new key
            S->>R: savepoint("op")
            S->>R: get_wallet(source), get_wallet(destination)
            alt business rule fails (404, 422)
                S->>R: rollback_to("op")
                S->>R: insert_idempotency(key, fingerprint, 4xx, error body)
            else all checks pass
                S->>R: last_transaction() for seq and prev_hash
                S->>S: chain_hash(prev_hash, tx, entries)
                S->>R: insert_transaction, insert_entry x2, set_balance x2
                S->>R: insert_idempotency(key, fingerprint, 201, body, tx id)
            end
            S->>R: commit()
            R->>D: COMMIT (synchronous=FULL: on disk before returning)
            S-->>A: Outcome(status, body)
        end
    end
    A-->>C: JSON body, status, Idempotent-Replayed if replayed
```

## Class diagram

```mermaid
classDiagram
    class LedgerService {
        +create_account(name) dict
        +create_wallet(account_id, currency) dict
        +get_wallet(wallet_id) dict
        +list_entries(wallet_id, limit, after_id) dict
        +get_transaction(transaction_id) dict
        +deposit(wallet_id, amount_minor, idem) Outcome
        +transfer(source, destination, amount_minor, idem) Outcome
        +reverse(transaction_id, reason, admin_id, idem) Outcome
        -_keyed(idem, work) Outcome
        -_post(type, legs, reverses_id, admin_id, reason) tuple
    }
    class LedgerRepository {
        +conn
        +begin_immediate()
        +begin_read()
        +commit()
        +rollback()
        +savepoint(name)
        +rollback_to(name)
        +get_wallet(id)
        +set_balance(id, balance)
        +last_transaction()
        +insert_transaction(tx)
        +insert_entry(tx_id, entry) int
        +get_idempotency(key)
        +insert_idempotency(...)
        +admin_exists(admin_id) bool
    }
    class IdempotencyRequest {
        +key: str
        +fingerprint: str
    }
    class Outcome {
        +status: int
        +body: dict
        +replayed: bool
    }
    class LedgerError {
        +code: str
        +message: str
        +status: int
        +stored_with_key: bool
        +body() dict
    }
    class reconciliation {
        <<module>>
        +reconcile(conn) dict
    }
    class hashing {
        <<module>>
        +chain_hash(prev_hash, tx, entries) str
        +request_fingerprint(method, path, body) str
        +canonical_json(value) bytes
    }
    class money {
        <<module>>
        +parse_amount(value) int
        +parse_currency(value) str
        +format_minor(amount, currency) str
    }
    LedgerService --> LedgerRepository : uses
    LedgerService ..> IdempotencyRequest : takes
    LedgerService ..> Outcome : returns
    LedgerService ..> LedgerError : raises
    LedgerService ..> hashing
    LedgerService ..> money
    reconciliation --> LedgerRepository : reads
    reconciliation ..> hashing : recomputes hashes
```

## How to use it from FastAPI

```python
from app.db.connection import connect, init_db
from app.errors import LedgerError
from app.ledger.hashing import request_fingerprint
from app.ledger.reconciliation import reconcile
from app.ledger.service import IdempotencyRequest, LedgerService

init_db(DB_PATH)                     # once at startup (migrations + internal wallets)
conn = connect(DB_PATH)              # one connection per request (or per worker thread)
svc = LedgerService(conn)

# POST /transfers
idem = IdempotencyRequest(request.headers.get("Idempotency-Key"),
                          request_fingerprint("POST", "/transfers", body))
try:
    out = svc.transfer(body.get("source_wallet_id"), body.get("destination_wallet_id"),
                       body.get("amount_minor"), idem)
    headers = {"Idempotent-Replayed": "true"} if out.replayed else {}
    return JSONResponse(out.body, status_code=out.status, headers=headers)
except LedgerError as err:
    return JSONResponse(err.body(), status_code=err.status)
```

### Methods

| Method | Returns | SRS | Notes |
|---|---|---|---|
| `create_account(name)` | dict | FR-1.1 | 201 |
| `create_wallet(account_id, currency)` | dict | FR-1.2 | 201; 404 `ACCOUNT_NOT_FOUND`, 409 `WALLET_EXISTS` |
| `get_wallet(wallet_id)` | dict | FR-1.5, FR-1.6 | 200 |
| `list_entries(wallet_id, limit=50, after_id=None)` | dict with `entries`, `next_after_id` | FR-4.6 | limit 1–500 |
| `get_transaction(transaction_id)` | dict with `entries`, `reversed_by` | FR-4.7 | |
| `deposit(wallet_id, amount_minor, idem)` | `Outcome` | FR-1.4 | keyed |
| `transfer(source, destination, amount_minor, idem)` | `Outcome` | FR-2, FR-3 | keyed |
| `reverse(transaction_id, reason, admin_id, idem)` | `Outcome` | FR-4.2, FR-4.3 | keyed; call **after** admin auth, pass `admin_keys.id` |
| `reconcile(conn)` | report dict | FR-5 | call after admin auth; always 200 |

### Outcome vs LedgerError

| You get | Meaning | Send |
|---|---|---|
| `Outcome(status=201, replayed=False)` | Done now | `body`, 201 |
| `Outcome(replayed=True)` | Same key + same body seen before | stored status and body, plus `Idempotent-Replayed: true` |
| `Outcome(status=404/409/422)` | Business rejection, **stored** with the key (FR-2.3) | `body`, that status |
| `raise LedgerError` | Not stored: 400, 401, 409 `IDEMPOTENCY_KEY_REUSED`, 503 (FR-2.6) | `err.body()`, `err.status` |

### Things the API layer still owns
- Pass the **raw** JSON values. Do not let Pydantic coerce `"100"` or `100.0` to `100` (FR-2.7, ADR 0001): use `StrictInt` or `Any`.
- Reject unknown JSON fields (NFR-11).
- Admin authentication (NFR-9, NFR-9a): hash `X-Admin-Key` with SHA-256, look it up in `admin_keys` where `revoked_at IS NULL`, return 401 if not found, **before** calling `reverse` or `reconcile`.
- Never return stack traces (NFR-13): catch unexpected exceptions and return 500 with a generic body.

## Guarantees (tested)

| Guarantee | Test |
|---|---|
| Debits = credits; SYSTEM wallet funds deposits | `test_ledger_service.py` |
| Retry replays, different body → 409, rejections stored, 400s not stored | `test_ledger_service.py` |
| 20 simultaneous transfers on 50000: exactly 5 succeed, balance 0 | `test_concurrency_and_rollback.py` |
| Lock wait over the busy timeout → 503, nothing written | `test_concurrency_and_rollback.py` |
| Failure at any write step leaves nothing (TQ-2) | `test_concurrency_and_rollback.py` |
| History cannot be updated or deleted | `test_schema.py` |
| Reconciliation passes on normal data, fails on tampering and names the transaction (TQ-10) | `test_reconciliation.py` |
| A 201'd transfer survives a hard kill; a kill mid-transfer leaves nothing (TQ-12, NFR-6) | `test_durability.py` |
| simulate-transfer skill: pass, broken race, wrong key, no server (SK-6, SK-8) | `test_simulate_transfer_skill.py` |

## Not done here (by design)
- FastAPI routes, admin-key CLI, OpenAPI: API owner.
- CI, end-to-end HTTP tests, local-check: Quality owner.
- FR-6 FX logic: waits for BR-9. The schema already has `fx_rates`, FX clearing wallets and `transactions.fx_rate_id`.
