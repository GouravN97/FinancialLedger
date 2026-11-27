---
type: research
title: Hash chains for tamper evidence
tags: [security, hashing, audit]
requirements: [FR-4, FR-5]
sources:
  - FIPS 180-4, Secure Hash Standard (SHA-256)
  - https://en.wikipedia.org/wiki/Hash_chain
  - https://datatracker.ietf.org/doc/html/rfc8785 (JSON canonicalization, background)
author: VishudhaSood
created: 2026-11-27
---

## Summary
A cryptographic hash such as SHA-256 maps any input to a fixed 64-hex-character value, and changing even one bit of the input changes the output unpredictably. In a hash chain, each record stores the hash of its own content together with the previous record's hash. Editing any old record changes its hash, which no longer matches the next record's stored `prev_hash`, so the break is visible. Triggers stop changes made through SQL; the hash chain detects changes made by editing the database file directly.

## Key points
- `hash_n = SHA-256(hash_(n-1) ∥ content_n)`, with 64 zeros before the first record.
- The content must be serialised the same way every time (canonical JSON: sorted keys, no spaces, UTF-8), or honest re-computation would disagree.
- Every field that matters must be inside the hashed content; a field left out can be changed undetected.
- A hash chain shows *that* something changed and where the first break is; it does not show what the old value was.
- Deleting the last records is not visible from the chain alone, which is why the reconciliation report also gives the latest sequence number and hash, so a later report can be compared.

## How it applies to our project
- `app/ledger/hashing.py` builds the canonical JSON from the transaction's id, seq, type, reverses_id, fx_rate_id, admin_id, reason and created_at, plus each entry's wallet_id, direction, amount_minor and balance_after (FR-4.5, ADR 0002).
- Reconciliation check (g) recomputes every hash and names the first transaction that does not match (FR-5.2); the tamper test (TQ-10) proves it.

## Related
- [[FR-4]] [[FR-5]]
- [[double-entry-ledger]]
