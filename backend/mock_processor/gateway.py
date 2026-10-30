"""Public in-process API of the simulated processor.

This is the ONLY module the payments app is allowed to touch. It exposes plain
dataclasses and functions — never Django models — so the payments app treats
the processor as an opaque external system. In a production system these calls
would be HTTPS requests to Stripe/Adyen; the in-process seam keeps the same
shape.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from . import outcomes
from .models import ProcessorCharge, ProcessorToken


class ProcessorError(Exception):
    """Raised for processor-side failures (e.g. unknown token)."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class ChargeResult:
    """Result of accepting a charge. Carries no sensitive data."""

    processor_reference: str
    method: str
    last4: str
    brand_or_bank_type: str
    status: str  # always "pending" at acceptance; final status arrives via webhook


@dataclass(frozen=True)
class ChargeStatus:
    """Current known outcome of a charge, used by replay/simulation."""

    processor_reference: str
    status: str
    failure_code: str | None


def charge(token: str, amount_minor: int, currency: str) -> ChargeResult:
    """Accept a charge against a previously issued token.

    The charge is always accepted as ``pending``; the final outcome is decided
    now (from the token's last4) and delivered later via webhook.
    """
    try:
        token_row = ProcessorToken.objects.get(pk=token)
    except ProcessorToken.DoesNotExist as exc:
        raise ProcessorError("invalid_token", "Unknown payment token") from exc

    outcome = outcomes.outcome_for(token_row.method, token_row.last4)
    reference = "pr_" + secrets.token_hex(16)
    ProcessorCharge.objects.create(
        processor_reference=reference,
        token=token_row,
        method=token_row.method,
        last4=token_row.last4,
        brand_or_bank_type=token_row.brand_or_bank_type,
        amount_minor=amount_minor,
        currency=currency,
        final_status=outcome.final_status,
        failure_code=outcome.failure_code,
        pending_delay_seconds=outcome.pending_delay_seconds,
    )
    return ChargeResult(
        processor_reference=reference,
        method=token_row.method,
        last4=token_row.last4,
        brand_or_bank_type=token_row.brand_or_bank_type,
        status=outcomes.PENDING,
    )


def get_charge_status(reference: str) -> ChargeStatus:
    """Return the final (terminal) outcome the processor holds for a charge."""
    try:
        row = ProcessorCharge.objects.get(pk=reference)
    except ProcessorCharge.DoesNotExist as exc:
        raise ProcessorError("unknown_reference", "Unknown processor reference") from exc
    return ChargeStatus(
        processor_reference=row.processor_reference,
        status=row.final_status,
        failure_code=row.failure_code,
    )
