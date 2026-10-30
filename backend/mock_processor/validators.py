"""Pure validation helpers for card and bank details.

None of these functions persist or log the raw values they receive. They are
used only inside the processor boundary (the ``tokenize`` endpoint); the
payments app never sees raw card or bank numbers.
"""

from __future__ import annotations

import datetime


class ValidationError(Exception):
    """Raised when card/bank details fail validation.

    The ``code`` attribute carries a machine-readable error such as
    ``invalid_number`` or ``invalid_expiry`` that the API surfaces to callers.
    """

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def luhn_valid(number: str) -> bool:
    """Return True if ``number`` (digits only) passes the Luhn checksum."""
    if not number.isdigit():
        return False
    digits = [int(d) for d in number]
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def detect_card_brand(number: str) -> str:
    """Best-effort card brand detection from the leading digits."""
    if number.startswith("4"):
        return "visa"
    if number[:2] in {"34", "37"}:
        return "amex"
    if number[:2] in {"51", "52", "53", "54", "55"} or "2221" <= number[:4] <= "2720":
        return "mastercard"
    if number.startswith("6"):
        return "discover"
    return "unknown"


def validate_card(number: str, exp_month: int, exp_year: int, cvv: str) -> tuple[str, str]:
    """Validate raw card details.

    Returns ``(last4, brand)``. Raises ``ValidationError`` with an appropriate
    code on failure. The raw number/cvv are never stored or logged.
    """
    number = (number or "").replace(" ", "").replace("-", "")
    if not number.isdigit() or not (12 <= len(number) <= 19) or not luhn_valid(number):
        raise ValidationError("invalid_number", "Card number failed Luhn validation")

    try:
        exp_month = int(exp_month)
        exp_year = int(exp_year)
    except (TypeError, ValueError) as exc:
        raise ValidationError("invalid_expiry", "Expiry is not a valid date") from exc

    if exp_year < 100:  # allow 2-digit years like 29 -> 2029
        exp_year += 2000
    if not (1 <= exp_month <= 12):
        raise ValidationError("invalid_expiry", "Expiry month out of range")

    today = datetime.date.today()
    # A card is valid through the last day of its expiry month.
    if (exp_year, exp_month) < (today.year, today.month):
        raise ValidationError("invalid_expiry", "Card has expired")

    cvv = str(cvv or "")
    if not cvv.isdigit() or not (3 <= len(cvv) <= 4):
        raise ValidationError("invalid_cvv", "CVV must be 3 or 4 digits")

    return number[-4:], detect_card_brand(number)


def validate_bank(account_number: str, routing_number: str) -> str:
    """Validate raw bank details. Returns ``last4`` of the account number."""
    routing_number = str(routing_number or "")
    if not routing_number.isdigit() or len(routing_number) != 9:
        raise ValidationError("invalid_routing", "Routing number must be exactly 9 digits")

    account_number = str(account_number or "")
    if not account_number.isdigit() or not (4 <= len(account_number) <= 17):
        raise ValidationError("invalid_account", "Account number is invalid")

    return account_number[-4:]
