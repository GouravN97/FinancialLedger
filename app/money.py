"""Money utility (SRS v1.1: C-3, NFR-8, BR-3, BR-4, FR-2.7).

Money is always an int count of minor units (paise for INR, cents for USD
and EUR). Nothing in this module ever produces or accepts a float.
"""

from __future__ import annotations

from app.errors import LedgerError

SUPPORTED_CURRENCIES = ("INR", "USD", "EUR")  # BR-3
MINOR_UNITS_PER_MAJOR = 100                    # all three have 2 decimals (BR-3)
MIN_AMOUNT_MINOR = 1                           # BR-4
MAX_AMOUNT_MINOR = 100_000_000                 # BR-4: ₹10,00,000.00 or $1,000,000.00

_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€"}


def parse_amount(value: object, field: str = "amount_minor") -> int:
    """Return value as an amount in minor units, or raise VALIDATION_ERROR.

    Accepts only a real int from 1 to 100,000,000 (FR-2.7, BR-4).
    Rejects floats (even 100.0), strings (even "100"), booleans and None,
    because JSON decoding turns 100.0 into a float and "100" into a str.
    """
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise LedgerError(
            "VALIDATION_ERROR",
            f"{field} must be a whole number of minor units (got {type(value).__name__})",
        )
    if not MIN_AMOUNT_MINOR <= value <= MAX_AMOUNT_MINOR:
        raise LedgerError(
            "VALIDATION_ERROR",
            f"{field} must be between {MIN_AMOUNT_MINOR} and {MAX_AMOUNT_MINOR}",
        )
    return value


def parse_currency(value: object, field: str = "currency") -> str:
    """Return a supported ISO 4217 code, or raise VALIDATION_ERROR (BR-3)."""
    if not isinstance(value, str) or value not in SUPPORTED_CURRENCIES:
        raise LedgerError(
            "VALIDATION_ERROR",
            f"{field} must be one of {', '.join(SUPPORTED_CURRENCIES)}",
        )
    return value


def format_minor(amount_minor: int, currency: str) -> str:
    """Format minor units for people, e.g. 10050 INR -> '₹100.50'.

    Uses integer division only, so no rounding can happen.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise TypeError("amount_minor must be an int")
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(amount_minor), MINOR_UNITS_PER_MAJOR)
    return f"{sign}{_SYMBOLS.get(currency, currency + ' ')}{major:,}.{minor:02d}"
