"""Error type shared by the service layer (SRS v1.1, Section 3.4).

Every error carries the HTTP status and the machine-readable code from the
SRS table, so the API layer can turn it into
{"error": {"code": ..., "message": ...}} without knowing any money rules.
"""

from __future__ import annotations

# Codes from SRS v1.1 Section 3.4, with their HTTP status.
STATUS_BY_CODE = {
    "VALIDATION_ERROR": 400,
    "IDEMPOTENCY_KEY_REQUIRED": 400,
    "SAME_WALLET": 400,
    "UNAUTHORIZED": 401,
    "ACCOUNT_NOT_FOUND": 404,
    "WALLET_NOT_FOUND": 404,
    "TRANSACTION_NOT_FOUND": 404,
    "WALLET_EXISTS": 409,
    "IDEMPOTENCY_KEY_REUSED": 409,
    "ALREADY_REVERSED": 409,
    "INSUFFICIENT_FUNDS": 422,
    "CURRENCY_MISMATCH": 422,
    "FX_RATE_NOT_FOUND": 422,
    "AMOUNT_TOO_SMALL": 422,
    "SYSTEM_WALLET_NOT_ALLOWED": 422,
    "CANNOT_REVERSE_REVERSAL": 422,
    "SERVICE_BUSY": 503,
    "SERVICE_UNAVAILABLE": 503,
}

# Rejections that happen at the business checks. For key-carrying requests
# these are stored with the idempotency key, so a retry gets the same answer
# (FR-2.3). Everything else (400, 401, 409 IDEMPOTENCY_KEY_REUSED, 503, 500)
# is never stored (FR-2.6).
STORED_REJECTION_CODES = frozenset({
    "ACCOUNT_NOT_FOUND",
    "WALLET_NOT_FOUND",
    "TRANSACTION_NOT_FOUND",
    "ALREADY_REVERSED",
    "INSUFFICIENT_FUNDS",
    "CURRENCY_MISMATCH",
    "FX_RATE_NOT_FOUND",
    "AMOUNT_TOO_SMALL",
    "SYSTEM_WALLET_NOT_ALLOWED",
    "CANNOT_REVERSE_REVERSAL",
})


class LedgerError(Exception):
    """A request the ledger refuses, with its SRS error code."""

    def __init__(self, code: str, message: str):
        if code not in STATUS_BY_CODE:
            raise ValueError(f"Unknown error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status(self) -> int:
        return STATUS_BY_CODE[self.code]

    @property
    def stored_with_key(self) -> bool:
        return self.code in STORED_REJECTION_CODES

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}

    def __repr__(self) -> str:
        return f"LedgerError({self.code!r}, {self.message!r})"
