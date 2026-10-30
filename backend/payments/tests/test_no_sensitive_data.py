"""Prove that a full payment flow never persists or logs sensitive data."""

import io
import logging

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from payments.models import Payment

from . import helpers


# A distinctive, Luhn-valid card plus a CVV and bank account we can grep for.
FULL_CARD = "4242424242424242"
CVV = "321"
FULL_ACCOUNT = "000111222333"
ROUTING = "110000000"


class NoSensitiveDataTests(TestCase):
    def _run_full_flow(self):
        # Tokenize a card and a bank account directly against the processor.
        self.client.post(
            reverse("mock_processor:tokenize"),
            data={"number": FULL_CARD, "exp_month": 12, "exp_year": 2099, "cvv": CVV},
            content_type="application/json",
        )
        bank_token = helpers.tokenize_bank(
            self.client, account_number=FULL_ACCOUNT, routing=ROUTING
        )
        card_token = helpers.tokenize_card(self.client)

        for token in (card_token, bank_token):
            resp, _ = helpers.create_payment(self.client, token)
            reference = resp.json()["processor_reference"]
            helpers.post_webhook(self.client, helpers.make_event(reference, "succeeded"))

    def _all_db_text(self) -> str:
        chunks = []
        for model in apps.get_models():
            for row in model.objects.all():
                chunks.append(str(vars(row)))
        return "\n".join(chunks)

    def test_no_sensitive_data_in_db(self):
        self._run_full_flow()
        blob = self._all_db_text()
        self.assertNotIn(FULL_CARD, blob)
        self.assertNotIn(CVV, blob)
        self.assertNotIn(FULL_ACCOUNT, blob)
        # The non-sensitive last4 is allowed and expected to be present.
        self.assertIn("4242", blob)

    def test_response_snapshot_has_no_sensitive_data(self):
        self._run_full_flow()
        for payment in Payment.objects.all():
            snapshot = str(payment.response_snapshot)
            self.assertNotIn(FULL_CARD, snapshot)
            self.assertNotIn(CVV, snapshot)
            self.assertNotIn(FULL_ACCOUNT, snapshot)

    def test_no_sensitive_data_in_logs(self):
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(handler)
        previous_level = root.level
        root.setLevel(logging.DEBUG)
        try:
            self._run_full_flow()
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        logged = buffer.getvalue()
        self.assertNotIn(FULL_CARD, logged)
        self.assertNotIn(CVV, logged)
        self.assertNotIn(FULL_ACCOUNT, logged)
