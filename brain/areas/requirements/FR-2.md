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
- SRS section: <link>
- Issue(s): <link>
- PR(s): <link>
- Test(s): <path>
- Skill(s): simulate-transfer
- ADR(s): <link to docs/adr/...>

## Research notes
- [[idempotency-keys]]