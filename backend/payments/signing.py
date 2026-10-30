"""Webhook signature verification (payments side).

Verifies the ``X-Processor-Signature`` header against the raw request body using
HMAC-SHA256 keyed with ``PROCESSOR_WEBHOOK_SECRET``. Implemented independently
of the processor so the two apps stay decoupled.
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings


def expected_signature(body: bytes) -> str:
    secret = settings.PROCESSOR_WEBHOOK_SECRET.encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def is_valid_signature(body: bytes, provided: str | None) -> bool:
    """Constant-time comparison of the provided signature against the expected."""
    if not provided:
        return False
    return hmac.compare_digest(expected_signature(body), provided)
