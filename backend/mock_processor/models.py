"""Internal persistence for the simulated processor.

IMPORTANT BOUNDARY: these models belong to the processor only. The payments
app must never import them or read these tables. The only supported entry point
for the payments app is :mod:`mock_processor.gateway`, which returns plain
dataclasses.

No full card numbers, CVVs, or full bank account numbers are stored here — only
the last four digits and non-sensitive metadata.
"""

from __future__ import annotations

from django.db import models


class ProcessorToken(models.Model):
    """A tokenized payment instrument. Holds no sensitive data."""

    CARD = "card"
    BANK = "bank"
    METHOD_CHOICES = [(CARD, "Card"), (BANK, "Bank")]

    token = models.CharField(max_length=64, primary_key=True)
    method = models.CharField(max_length=8, choices=METHOD_CHOICES)
    last4 = models.CharField(max_length=4)
    brand_or_bank_type = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.token} ({self.method} ****{self.last4})"


class ProcessorCharge(models.Model):
    """A charge request against a token, with its pre-decided final outcome."""

    processor_reference = models.CharField(max_length=64, primary_key=True)
    token = models.ForeignKey(ProcessorToken, on_delete=models.PROTECT, related_name="charges")
    method = models.CharField(max_length=8)
    last4 = models.CharField(max_length=4)
    brand_or_bank_type = models.CharField(max_length=32)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)

    final_status = models.CharField(max_length=16)
    failure_code = models.CharField(max_length=32, null=True, blank=True)  # noqa: DJ001
    pending_delay_seconds = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.processor_reference} -> {self.final_status}"
