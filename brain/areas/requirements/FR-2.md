---
type: requirement
title: FR-2 Idempotent transfers
tags:
  - requirement
  - api
requirements:
  - "[FR-2]"
created: 2026-11-08
author: GouravN97
---

## Statement
Transfer funds between two wallets. The endpoint requires an Idempotency-Key header so retried requests never double-charge.

## Trace
- SRS section: SRS v1.1 Section 4 (FR-2)
- Issue(s): <link>
- PR(s): <link>
- Test(s): tests/test_ledger_service.py (FR-2 section)
- Skill(s): simulate-transfer
- ADR(s): docs/adr/0001-money-representation.md

## Research notes
- [[idempotency-keys]]
- [[money-minor-units]] [[sqlite-transactions-and-locking]]
