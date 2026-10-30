"""Payment and append-only ledger models.

The ledger is append-only. This is enforced at two layers:

1. Application layer: :meth:`LedgerEntry.save` rejects updates and
   :meth:`LedgerEntry.delete` is disabled.
2. Database layer (authoritative): a Postgres trigger raises on any
   ``UPDATE`` or ``DELETE`` against the ledger table. See migration
   ``0002_ledger_append_only``.

At-most-once webhook processing and single-ledger-entry-per-event are enforced
by a partial unique index on ``event_id``.
"""

from __future__ import annotations

import uuid

from django.db import models

from common.models import IndexedTimeStampedModel

from . import state


class Payment(IndexedTimeStampedModel):
    STATUS_CHOICES = [(s, s) for s in state.ALL_STATUSES]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    amount_minor = models.BigIntegerField(help_text="Amount in integer minor units (cents)")
    currency = models.CharField(max_length=3, default="USD")

    # Non-sensitive instrument metadata (never the full PAN / account number).
    payment_token = models.CharField(max_length=64)
    method = models.CharField(max_length=8, blank=True)
    last4 = models.CharField(max_length=4, blank=True)
    brand_or_bank_type = models.CharField(max_length=32, blank=True)

    processor_reference = models.CharField(max_length=64, unique=True, null=True, blank=True)  # noqa: DJ001

    # Idempotency.
    idempotency_key = models.CharField(max_length=255, unique=True)
    request_fingerprint = models.CharField(max_length=64)
    response_snapshot = models.JSONField(default=dict, blank=True)

    # Cache of the status derived from the ledger (ledger is authoritative).
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=state.PENDING)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created"]),
        ]

    def __str__(self) -> str:
        return f"Payment {self.id} {self.amount_minor} {self.currency} [{self.status}]"

    def ordered_ledger(self):
        """Ledger entries in insertion (sequence) order."""
        return self.ledger_entries.order_by("id")

    def derive_status(self) -> str:
        """Recompute the status purely from the ledger."""
        return state.derive_status(list(self.ordered_ledger()))


class LedgerEntry(IndexedTimeStampedModel):
    """An immutable record of one lifecycle/processor event for a payment.

    ``id`` (BigAutoField) doubles as the monotonic per-table sequence used to
    order the fold that derives the payment status.
    """

    EVENT_TYPE_CHOICES = [
        (state.PAYMENT_CREATED, "Payment created"),
        (state.PROCESSOR_WEBHOOK, "Processor webhook"),
        (state.REPLAY_REQUESTED, "Replay requested"),
    ]

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="ledger_entries")
    event_type = models.CharField(max_length=32, choices=EVENT_TYPE_CHOICES)
    # The status reported by this event (pending / succeeded / failed).
    status = models.CharField(max_length=16, choices=Payment.STATUS_CHOICES)
    failure_code = models.CharField(max_length=32, null=True, blank=True)  # noqa: DJ001

    # Processor-supplied idempotency key. NULL for internally generated entries
    # (e.g. payment_created). Unique when present -> at-most-once processing.
    event_id = models.CharField(max_length=128, null=True, blank=True)  # noqa: DJ001

    # When the event occurred at the processor (may differ from `created`).
    occurred_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["event_id"],
                condition=models.Q(event_id__isnull=False),
                name="uniq_ledger_event_id",
            ),
        ]
        indexes = [
            models.Index(fields=["payment", "id"]),
        ]
        verbose_name_plural = "ledger entries"

    def __str__(self) -> str:
        return f"Ledger#{self.id} {self.payment_id} {self.event_type}:{self.status}"

    def save(self, *args, **kwargs):
        # Append-only: reject updates to an already-persisted row.
        if self.pk is not None and not self._state.adding:
            raise ValueError("LedgerEntry is append-only; updates are not permitted")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("LedgerEntry is append-only; deletes are not permitted")
