---
type: research
title: Storing money as integer minor units
tags: [money, data-types]
requirements: [FR-2, NFR-8]
sources:
  - https://docs.python.org/3/tutorial/floatingpoint.html
  - https://www.sqlite.org/datatype3.html
  - ISO 4217 currency codes
author: VishudhaSood
created: 2026-11-27
---

## Summary
Binary floating point cannot represent most decimal fractions exactly: in Python `0.1 + 0.2` is `0.30000000000000004`. Rounding errors like this are unacceptable for money because they can create or destroy fractions of a paisa over many operations. The standard fix is to store the smallest unit of the currency as an integer: ₹100.50 is stored as 10050 paise. Integer addition and subtraction are exact.

## Key points
- INR, USD and EUR all have 2 decimal places, so 1 major unit = 100 minor units.
- JSON has one number type; Python decodes `100.0` as a float and `"100"` as a string, so the API must reject both explicitly.
- In Python, `bool` is a subclass of `int`, so `True` would pass a naive `isinstance(x, int)` check.
- SQLite uses type affinity: an INTEGER column silently stores `100.0` as `100` and `"100"` as `100`, but stores `100.5` as REAL. A `CHECK (typeof(col) = 'integer')` constraint catches the REAL case.
- Formatting for people uses `divmod(amount, 100)`, never division into a float.

## How it applies to our project
- `app/money.py`: `parse_amount` accepts only real ints from 1 to 100,000,000 (FR-2.7, BR-4).
- Every money column in `001_init.sql` has a `typeof = 'integer'` CHECK (NFR-8, DB-2).
- Decision recorded in ADR 0001.

## Related
- [[double-entry-ledger]]
- [[FR-2]]
