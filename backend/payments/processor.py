"""Adapter to the external payment processor.

This is the ONLY module in the payments app that knows about the processor
implementation. It deliberately depends on :mod:`mock_processor.gateway`
(plain functions + dataclasses) and never on the processor's models or tables.
Swapping in a real Stripe/Adyen client means replacing only this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from mock_processor import gateway
from mock_processor.gateway import ProcessorError  # re-exported for callers


@dataclass(frozen=True)
class ChargeResult:
    processor_reference: str
    method: str
    last4: str
    brand_or_bank_type: str
    status: str


@dataclass(frozen=True)
class ChargeStatus:
    processor_reference: str
    status: str
    failure_code: str | None


class ProcessorClient:
    """Thin, swappable wrapper around the processor's public API."""

    def charge(self, token: str, amount_minor: int, currency: str) -> ChargeResult:
        result = gateway.charge(token, amount_minor, currency)
        return ChargeResult(
            processor_reference=result.processor_reference,
            method=result.method,
            last4=result.last4,
            brand_or_bank_type=result.brand_or_bank_type,
            status=result.status,
        )

    def get_charge_status(self, reference: str) -> ChargeStatus:
        status = gateway.get_charge_status(reference)
        return ChargeStatus(
            processor_reference=status.processor_reference,
            status=status.status,
            failure_code=status.failure_code,
        )


_client = ProcessorClient()


def get_client() -> ProcessorClient:
    return _client


__all__ = ["ChargeResult", "ChargeStatus", "ProcessorClient", "ProcessorError", "get_client"]
