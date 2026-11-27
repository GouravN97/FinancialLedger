---
type: research
title: Double-entry ledger
tags: [ledger, accounting]
requirements: [FR-1, FR-4, FR-5]
sources:
  - https://en.wikipedia.org/wiki/Double-entry_bookkeeping
  - Project_2_Financial_Ledger.pdf (course brief)
author: VishudhaSood
created: 2026-11-27
---

## Summary
Double-entry bookkeeping records every movement of money twice: once as a debit on the account it leaves and once as an equal credit on the account it enters. Because each movement adds the same amount to both sides, total debits always equal total credits. A balance is never stored as a free-standing fact; it is the sum of the entries, so it can always be recomputed and checked. This is what makes a ledger auditable.

## Key points
- One transaction = two or more entries whose debits and credits are equal (per currency).
- Debit = money leaves a wallet, credit = money enters it (the convention in our team plan).
- Money from outside the system needs a counter-account: our SYSTEM wallet is debited on every deposit, so it goes negative by exactly the amount that has entered.
- Mistakes are never fixed by editing; a new transaction with opposite entries (a reversal) cancels the old one.
- If the stored balance ever differs from credits minus debits, something bypassed the rules.

## How it applies to our project
- `LedgerService._post` refuses any posting whose debits and credits differ per currency (BR-1).
- Deposits debit the SYSTEM wallet and credit the user wallet (FR-1.4).
- Reconciliation checks (a), (b) and (c) are exactly the double-entry invariants (FR-5.2).
- Example: Asha deposits ₹500, then sends ₹100 to Ravi → SYSTEM −50000, Asha 40000, Ravi 10000; sum = 0.

## Related
- [[FR-1]] [[FR-4]] [[FR-5]]
- [[money-minor-units]]
