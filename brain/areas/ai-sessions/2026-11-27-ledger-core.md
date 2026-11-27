---
type: ai-session
title: Building the ledger core with Claude
tags:
  - ai-session
requirements: [FR-1, FR-2, FR-3, FR-4, FR-5, DB-1, TQ-1, TQ-2, TQ-10]
author: VishudhaSood
tool: Claude (Anthropic)
created: 2026-11-27
---

## Goal
Write the Ledger-owner part of the project against SRS v1.1: schema migration, money utility, posting service with idempotency inside one BEGIN IMMEDIATE, hash chain, reversals, reconciliation, tests, two ADRs, four research notes and the brain-ingest skill.

## What worked
- Writing all checks before the first INSERT made rejections simple: nothing to undo.
- A SAVEPOINT lets a business rejection (422) be stored with its idempotency key while the rest is rolled back (FR-2.3).
- The 20-thread race test (FR-3.4) passed on every run with `BEGIN IMMEDIATE`.

## What failed or needed correcting
- SRS v1.1 FR-4.5 did not list the entry fields in the hash; fixed by ADR 0002 (wallet_id, direction, amount_minor, balance_after; entry id excluded).
- First version of the paging test assumed a full page could know there was nothing after it; corrected.
- Coverage (NFR-18) could not be measured locally without pytest-cov; left to CI.

## What a human reviewed and changed
- To fill in by Vishudha after reviewing the PR: what you read line by line, what you changed, and anything you could not explain yet.

## Links
- PR: (fill in)
- Related notes: [[double-entry-ledger]] [[money-minor-units]] [[sqlite-transactions-and-locking]] [[hash-chains]]
