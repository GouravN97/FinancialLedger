---
type: requirement
title: FR-1 Wallet Initialization
tags:
  - requirement
  - api
requirements:
  - "[FR-1]"
created: 2026-11-08
author: GouravN97
---

## Statement
Create user accounts with distinct currency wallets. Every balance is backed by double-entry ledger entries (every credit must equal a debit).

## Trace
- SRS section: SRS v1.1 Section 4 (FR-1)
- Issue(s): <link>
- PR(s): <link>
- Test(s): tests/test_ledger_service.py (FR-1 section)
- Skill(s): simulate-transfer
- ADR(s): docs/adr/0001-money-representation.md, docs/adr/0002-ledger-schema.md

## Research notes
- [[idempotency-keys]]
- [[double-entry-ledger]] [[money-minor-units]]
