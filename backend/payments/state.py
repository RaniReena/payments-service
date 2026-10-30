"""Payment state machine.

The payment status is derived **purely from the ledger** by folding each
recorded event through :func:`apply_transition`. ``Payment.status`` is only a
cache of this fold, maintained inside the same transaction that appends a
ledger row.

Rules:
    * A payment starts at ``PENDING`` when created.
    * ``pending -> succeeded`` or ``pending -> failed`` are the only state
      changes.
    * Terminal states (``succeeded`` / ``failed``) are final. Any later event
      — a late ``pending`` or a *conflicting* terminal — is recorded in the
      ledger for audit but never changes the status. First terminal wins.
"""

from __future__ import annotations

# Statuses
PENDING = "pending"
SUCCEEDED = "succeeded"
FAILED = "failed"
TERMINAL_STATUSES = frozenset({SUCCEEDED, FAILED})
ALL_STATUSES = (PENDING, SUCCEEDED, FAILED)

# Ledger entry types
PAYMENT_CREATED = "payment_created"
PROCESSOR_WEBHOOK = "processor_webhook"
REPLAY_REQUESTED = "replay_requested"


def apply_transition(current: str | None, event_status: str) -> str:
    """Return the resulting status after applying ``event_status``.

    ``current`` is ``None`` before the payment is created. Terminal states are
    sticky: once terminal, nothing changes them (first terminal wins).
    """
    if current in TERMINAL_STATUSES:
        return current
    if event_status == PENDING:
        return PENDING
    if event_status in TERMINAL_STATUSES:
        return event_status
    # Unknown event status: leave state untouched.
    return current if current is not None else PENDING


def derive_status(entries) -> str:
    """Fold an ordered iterable of ledger entries into the current status.

    ``entries`` must be ordered by insertion sequence (ledger ``id``). Each
    entry only needs a ``status`` attribute carrying the event's reported
    status.
    """
    status: str | None = None
    for entry in entries:
        status = apply_transition(status, entry.status)
    return status or PENDING
