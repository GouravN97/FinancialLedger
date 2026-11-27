# ADR 0001: Represent money as integer minor units

- Status: Accepted
- Date: 2026-11-27
- Author: Vishudha Sood (Ledger owner)
- Requirements: C-3, NFR-8, FR-2.7, BR-3, BR-4, TQ-6

## Context
The ledger must never create or lose money. Floating-point numbers cannot represent most decimal amounts exactly (`0.1 + 0.2 != 0.3`), and those errors build up over many operations. JSON has a single number type, and SQLite's INTEGER affinity silently converts some values, so the representation has to be enforced at the API, in Python and in the database. Research: [[money-minor-units]].

## Decision
1. Every amount is an `int` count of minor units of its currency (paise, cents). ₹100.50 is `10050`.
2. Supported currencies are INR, USD and EUR, all with 2 decimal places.
3. `app/money.parse_amount` accepts only a real `int` (not `bool`, `float` or `str`) from 1 to 100,000,000. Anything else is `400 VALIDATION_ERROR`.
4. Every money column has `CHECK (typeof(column) = 'integer')`.
5. Display formatting uses `divmod`, never float division.
6. Cross-currency conversion (FR-6, later) will use an integer `rate_scaled` and round down with integer division.

## Consequences
- Arithmetic is exact and reconciliation can compare totals with `==`.
- API clients must send `10050`, not `100.50`; the user guide must say so.
- The API layer must pass the raw decoded JSON value to `parse_amount` and must not let Pydantic coerce `"100"` or `100.0` into an int first (use `StrictInt` or validate in the service).

## Alternatives considered
- `float`: rejected, inexact.
- `decimal.Decimal`: exact, but SQLite has no decimal type, so it would be stored as text or converted back to float, and the course asks for integer minor units.
