"""Webhook signing (processor side).

The processor signs the exact raw bytes of the webhook body with
PROCESSOR_WEBHOOK_SECRET using HMAC-SHA256 and sends the hex digest in the
``X-Processor-Signature`` header. The payments app verifies independently (see
``payments.signing``) so neither side imports the other.
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings


def sign(body: bytes) -> str:
    secret = settings.PROCESSOR_WEBHOOK_SECRET.encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()
