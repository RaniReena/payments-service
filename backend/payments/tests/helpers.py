"""Shared helpers for payments tests.

Tokenization goes through the real ``/processor/tokenize`` endpoint so tests
respect the same boundary the production code does: the payments app only ever
sees a token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from django.conf import settings
from django.urls import reverse

from mock_processor import validators


def luhn_card_ending(last4: str, prefix: str = "4") -> str:
    fill = 16 - len(prefix) - len(last4)
    for i in range(10**fill):
        candidate = f"{prefix}{i:0{fill}d}{last4}"
        if validators.luhn_valid(candidate):
            return candidate
    raise AssertionError("could not build Luhn number")


def tokenize_card(client, last4: str = "4242", cvv: str = "123") -> str:
    number = "4242424242424242" if last4 == "4242" else luhn_card_ending(last4)
    resp = client.post(
        reverse("mock_processor:tokenize"),
        data={"method": "card", "number": number, "exp_month": 12, "exp_year": 2099, "cvv": cvv},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["token"]


def tokenize_bank(client, account_number: str = "000123456789", routing: str = "110000000") -> str:
    resp = client.post(
        reverse("mock_processor:tokenize"),
        data={"method": "bank", "account_number": account_number, "routing_number": routing},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["token"]


def create_payment(
    client, token: str, amount_minor: int = 1000, key: str | None = None, currency: str = "USD"
):
    key = key or ("idem_" + secrets.token_hex(8))
    resp = client.post(
        reverse("payments:payments"),
        data={"amount_minor": amount_minor, "currency": currency, "payment_token": token},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    return resp, key


def sign(body: bytes) -> str:
    secret = settings.PROCESSOR_WEBHOOK_SECRET.encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def make_event(
    reference: str,
    status: str,
    event_id: str | None = None,
    failure_code: str | None = None,
    occurred_at: str = "2026-09-28T10:15:02.113Z",
) -> dict:
    return {
        "event_id": event_id or ("evt_" + secrets.token_hex(12)),
        "processor_reference": reference,
        "status": status,
        "failure_code": failure_code,
        "occurred_at": occurred_at,
    }


def post_webhook(client, event: dict, signature: str | None = None, send_signature: bool = True):
    body = json.dumps(event).encode("utf-8")
    sig = signature if signature is not None else sign(body)
    headers = {"content_type": "application/json"}
    if send_signature:
        headers["HTTP_X_PROCESSOR_SIGNATURE"] = sig
    return client.generic("POST", reverse("payments:processor-webhook"), body, **headers)
