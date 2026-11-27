---
type: requirement
title: FR-4 Immutable Audit Trail
tags:
  - requirement
  - api
requirements:
  - "[FR-4]"
created: 2026-11-08
author: GouravN97
---

## Statement
Ledger records cannot be updated or deleted once written. Any corrections or cancellations must be recorded as an explicit reversal transaction.

## Trace
- SRS section: SRS v1.1 Section 4 (FR-4)
- Issue(s): <link>
- PR(s): <link>
- Test(s): tests/test_schema.py, tests/test_ledger_service.py (FR-4 section)
- Skill(s): simulate-transfer
- ADR(s): docs/adr/0002-ledger-schema.md

## Research notes
- [[idempotency-keys]]
- [[hash-chains]] [[double-entry-ledger]]
