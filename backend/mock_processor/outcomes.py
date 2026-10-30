"""Deterministic charge outcomes based on the last four digits.

Mirrors the assignment's test matrix. The outcome is decided from the payment
method and the last four digits that were captured at tokenization time.
"""

from __future__ import annotations

from dataclasses import dataclass


PENDING = "pending"
SUCCEEDED = "succeeded"
FAILED = "failed"

CARD = "card"
BANK = "bank"

# How long (seconds) the real processor stays pending before the final event.
SLOW_SETTLE_SECONDS = 15


@dataclass(frozen=True)
class Outcome:
    final_status: str
    failure_code: str | None
    pending_delay_seconds: int


def outcome_for(method: str, last4: str) -> Outcome:
    """Return the terminal outcome the processor will eventually report."""
    if last4 == "0002":
        code = "card_declined" if method == CARD else "insufficient_funds"
        return Outcome(FAILED, code, 0)
    if last4 == "0119":
        return Outcome(FAILED, "processor_error", 0)
    if last4 == "0341":
        return Outcome(SUCCEEDED, None, SLOW_SETTLE_SECONDS)
    return Outcome(SUCCEEDED, None, 0)
