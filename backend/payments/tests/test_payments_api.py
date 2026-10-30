from django.test import TestCase
from django.urls import reverse

from payments.models import LedgerEntry, Payment

from . import helpers


class PaymentCreationTests(TestCase):
    def test_create_payment_returns_pending_with_ledger(self):
        token = helpers.tokenize_card(self.client)
        resp, _ = helpers.create_payment(self.client, token, amount_minor=1500)
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["amount_minor"], 1500)
        self.assertEqual(body["last4"], "4242")
        self.assertTrue(body["processor_reference"].startswith("pr_"))
        # Exactly one creation ledger entry.
        self.assertEqual(len(body["ledger"]), 1)
        self.assertEqual(body["ledger"][0]["event_type"], "payment_created")

    def test_missing_idempotency_key_rejected(self):
        token = helpers.tokenize_card(self.client)
        resp = self.client.post(
            reverse("payments:payments"),
            data={"amount_minor": 1000, "currency": "USD", "payment_token": token},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "missing_idempotency_key")

    def test_non_usd_rejected(self):
        token = helpers.tokenize_card(self.client)
        resp, _ = helpers.create_payment(self.client, token, currency="EUR")
        self.assertEqual(resp.status_code, 400)


class IdempotencyTests(TestCase):
    def test_same_key_same_body_returns_same_payment(self):
        token = helpers.tokenize_card(self.client)
        resp1, key = helpers.create_payment(self.client, token, amount_minor=2000)
        self.assertEqual(resp1.status_code, 201)

        # Repeat with identical body + key.
        resp2, _ = helpers.create_payment(self.client, token, amount_minor=2000, key=key)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.json()["id"], resp2.json()["id"])

        # Nothing new was created.
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_same_key_different_body_rejected(self):
        token = helpers.tokenize_card(self.client)
        resp1, key = helpers.create_payment(self.client, token, amount_minor=2000)
        self.assertEqual(resp1.status_code, 201)

        resp2, _ = helpers.create_payment(self.client, token, amount_minor=9999, key=key)
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(resp2.json()["error"], "idempotency_key_reuse")
        self.assertEqual(Payment.objects.count(), 1)


class PaymentRetrievalTests(TestCase):
    def test_get_payment_returns_status_and_ledger(self):
        token = helpers.tokenize_card(self.client)
        resp, _ = helpers.create_payment(self.client, token)
        payment_id = resp.json()["id"]

        detail = self.client.get(reverse("payments:payment-detail", args=[payment_id]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "pending")
        self.assertEqual(len(detail.json()["ledger"]), 1)

    def test_get_unknown_payment_404(self):
        resp = self.client.get(
            reverse("payments:payment-detail", args=["00000000-0000-0000-0000-000000000000"])
        )
        self.assertEqual(resp.status_code, 404)
