"""Idempotency-key request fingerprinting.

Two requests carrying the same ``Idempotency-Key`` are considered the same
operation only if their meaningful request body is identical. We hash a
canonical form of the body so that key-reuse with a different body can be
detected and rejected.
"""

from __future__ import annotations

import hashlib
import json


def fingerprint(amount_minor: int, currency: str, payment_token: str) -> str:
    canonical = json.dumps(
        {
            "amount_minor": amount_minor,
            "currency": currency,
            "payment_token": payment_token,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
