# FinancialLedger

## Ledger core (service layer)

The ledger core (FR-1 to FR-5 money rules) lives in `app/`. See `docs/design/ledger-core.md` for how the API layer calls it.

```bash
python -m pip install pytest
python -m pytest -q
```

Tests always use a new temporary database (NFR-7).
