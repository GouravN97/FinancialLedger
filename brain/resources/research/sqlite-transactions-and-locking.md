---
type: research
title: SQLite transactions, BEGIN IMMEDIATE and WAL
tags: [sqlite, concurrency, acid]
requirements: [FR-3, NFR-5, NFR-6]
sources:
  - https://www.sqlite.org/lang_transaction.html
  - https://www.sqlite.org/wal.html
  - https://www.sqlite.org/pragma.html#pragma_synchronous
  - https://docs.python.org/3/library/sqlite3.html#transaction-control
author: VishudhaSood
created: 2026-11-27
---

## Summary
A database transaction groups statements so they apply completely or not at all (ACID). SQLite allows only one writer at a time. A plain `BEGIN` is deferred: it takes the write lock only at the first write, so two requests can both read the same balance first and then both write, which is the lost-update race. `BEGIN IMMEDIATE` takes the write lock at the start, before any read, so the second request waits until the first has committed and then sees the new balance.

## Key points
- `PRAGMA busy_timeout = 5000` makes a waiting connection retry for up to 5 s; after that SQLite reports "database is locked".
- WAL mode lets readers keep reading a consistent snapshot while one writer writes. A read transaction sees the database as it was at its first read.
- `PRAGMA synchronous = FULL` waits for the disk on every commit, so a committed transaction survives a power loss (slower, but durable).
- Python's `sqlite3` opens transactions implicitly unless `isolation_level=None`; we turn that off so the service controls `BEGIN IMMEDIATE` itself.
- SAVEPOINTs allow undoing part of a transaction while keeping the rest.
- Concurrency tests need a database file: each connection to `:memory:` is a separate database.

## How it applies to our project
- Every deposit, transfer and reversal runs inside one `BEGIN IMMEDIATE` (FR-3.1); the idempotency lookup, checks, entries, balances, hash and idempotency record all sit inside it.
- A lock wait over 5 s becomes 503 `SERVICE_BUSY` with nothing written (FR-3.3).
- A business rejection rolls back to a SAVEPOINT and stores only the idempotency record (FR-2.3).
- Reconciliation reads in one deferred transaction for a consistent snapshot (FR-5.1).

## Related
- [[FR-3]] [[FR-2]] [[FR-5]]
