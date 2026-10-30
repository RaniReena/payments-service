"""Transactional business logic for payments.

All invariants (idempotency, at-most-once webhooks, append-only ledger,
concurrency safety) are enforced here and by the database constraints the
models declare.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime

from . import state
from .idempotency import fingerprint
from .models import LedgerEntry, Payment
from .processor import ProcessorError, get_client
from .serializers import PaymentSerializer


logger = logging.getLogger(__name__)


class IdempotencyConflict(Exception):
    """Same Idempotency-Key reused with a different request body."""


class PaymentNotFound(Exception):
    pass


def _snapshot(payment: Payment) -> dict:
    return PaymentSerializer(payment).data


def create_payment(*, amount_minor: int, currency: str, payment_token: str, idempotency_key: str):
    """Create a payment idempotently.

    Returns ``(payment, created, response_body)``. ``created`` is False when an
    existing payment is returned for a repeated idempotency key (in which case
    ``response_body`` is the original stored response).

    Raises :class:`IdempotencyConflict` when the key is reused with a different
    body, and :class:`payments.processor.ProcessorError` on processor failure.
    """
    request_fingerprint = fingerprint(amount_minor, currency, payment_token)

    with transaction.atomic():
        existing = (
            Payment.objects.select_for_update()
            .filter(idempotency_key=idempotency_key)
            .first()
        )
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise IdempotencyConflict()
            return existing, False, existing.response_snapshot

        payment = Payment(
            amount_minor=amount_minor,
            currency=currency,
            payment_token=payment_token,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            status=state.PENDING,
        )
        try:
            with transaction.atomic():  # savepoint guarding the unique-key insert
                payment.save()
                # Charge the processor (in-process external call). Rolled back
                # with the savepoint if anything below fails.
                result = get_client().charge(payment_token, amount_minor, currency)
                payment.processor_reference = result.processor_reference
                payment.method = result.method
                payment.last4 = result.last4
                payment.brand_or_bank_type = result.brand_or_bank_type

                LedgerEntry.objects.create(
                    payment=payment,
                    event_type=state.PAYMENT_CREATED,
                    status=state.PENDING,
                )
                payment.status = payment.derive_status()
                payment.response_snapshot = _snapshot(payment)
                payment.save()
        except IntegrityError:
            # Lost the race to another request with the same key. Block until the
            # winner commits, then return its result (no second charge happened).
            winner = Payment.objects.select_for_update().get(idempotency_key=idempotency_key)
            if winner.request_fingerprint != request_fingerprint:
                raise IdempotencyConflict() from None
            return winner, False, winner.response_snapshot

        return payment, True, payment.response_snapshot


def process_webhook_event(event: dict) -> dict:
    """Apply one processor webhook event. Concurrency- and duplicate-safe.

    Returns a dict ``{"result": ..., "status": ...}``. ``result`` is one of
    ``processed``, ``duplicate_ignored``, ``unknown_reference``.
    """
    reference = event["processor_reference"]
    event_id = event["event_id"]
    event_status = event["status"]
    failure_code = event.get("failure_code")
    occurred_at = parse_datetime(event["occurred_at"]) if event.get("occurred_at") else None

    try:
        with transaction.atomic():
            # Serialize all processing for this payment on its row lock.
            payment = Payment.objects.select_for_update().get(processor_reference=reference)

            try:
                with transaction.atomic():  # savepoint for the unique event_id insert
                    LedgerEntry.objects.create(
                        payment=payment,
                        event_type=state.PROCESSOR_WEBHOOK,
                        status=event_status,
                        failure_code=failure_code,
                        event_id=event_id,
                        occurred_at=occurred_at,
                    )
            except IntegrityError:
                # event_id already processed -> exactly one ledger entry exists.
                return {"result": "duplicate_ignored", "status": payment.status}

            new_status = payment.derive_status()
            if new_status != payment.status:
                payment.status = new_status
                payment.save(update_fields=["status", "modified"])
            return {"result": "processed", "status": payment.status}
    except Payment.DoesNotExist:
        logger.warning("Webhook for unknown processor_reference=%s", reference)
        return {"result": "unknown_reference", "status": None}


def replay_payment(payment_id) -> dict:
    """Admin-only: re-request the result of a (possibly stuck) payment.

    Safe to call repeatedly: it records an audit entry and, if the processor
    now holds a terminal result, applies it via a deterministic event_id so a
    later real webhook for the same outcome is de-duplicated.
    """
    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(id=payment_id)
        except Payment.DoesNotExist as exc:
            raise PaymentNotFound() from exc

        LedgerEntry.objects.create(
            payment=payment,
            event_type=state.REPLAY_REQUESTED,
            status=payment.status,
        )

        if payment.status in state.TERMINAL_STATUSES or not payment.processor_reference:
            return {"result": "noop", "status": payment.status}

        try:
            charge_status = get_client().get_charge_status(payment.processor_reference)
        except ProcessorError:
            logger.exception("Replay could not reach processor for %s", payment_id)
            return {"result": "processor_unavailable", "status": payment.status}

        if charge_status.status in state.TERMINAL_STATUSES:
            deterministic_id = f"replay:{payment.processor_reference}:{charge_status.status}"
            try:
                with transaction.atomic():
                    LedgerEntry.objects.create(
                        payment=payment,
                        event_type=state.PROCESSOR_WEBHOOK,
                        status=charge_status.status,
                        failure_code=charge_status.failure_code,
                        event_id=deterministic_id,
                    )
            except IntegrityError:
                pass  # already applied
            new_status = payment.derive_status()
            if new_status != payment.status:
                payment.status = new_status
                payment.save(update_fields=["status", "modified"])

        return {"result": "replayed", "status": payment.status}
