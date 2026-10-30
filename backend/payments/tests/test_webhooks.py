from django.test import TestCase

from payments.models import LedgerEntry, Payment

from . import helpers


class WebhookSignatureTests(TestCase):
    def setUp(self):
        token = helpers.tokenize_card(self.client)
        resp, _ = helpers.create_payment(self.client, token)
        self.reference = resp.json()["processor_reference"]
        self.payment_id = resp.json()["id"]

    def test_missing_signature_rejected_without_change(self):
        event = helpers.make_event(self.reference, "succeeded")
        resp = helpers.post_webhook(self.client, event, send_signature=False)
        self.assertEqual(resp.status_code, 401)
        self._assert_unchanged()

    def test_invalid_signature_rejected_without_change(self):
        event = helpers.make_event(self.reference, "succeeded")
        resp = helpers.post_webhook(self.client, event, signature="deadbeef")
        self.assertEqual(resp.status_code, 401)
        self._assert_unchanged()

    def _assert_unchanged(self):
        payment = Payment.objects.get(id=self.payment_id)
        self.assertEqual(payment.status, "pending")
        self.assertEqual(payment.ledger_entries.count(), 1)  # only payment_created


class WebhookProcessingTests(TestCase):
    def setUp(self):
        token = helpers.tokenize_card(self.client)
        resp, _ = helpers.create_payment(self.client, token)
        self.reference = resp.json()["processor_reference"]
        self.payment_id = resp.json()["id"]

    def _status(self):
        return Payment.objects.get(id=self.payment_id).status

    def test_pending_then_succeeded(self):
        helpers.post_webhook(self.client, helpers.make_event(self.reference, "pending"))
        helpers.post_webhook(self.client, helpers.make_event(self.reference, "succeeded"))
        self.assertEqual(self._status(), "succeeded")

    def test_duplicate_event_id_writes_one_ledger_entry(self):
        event = helpers.make_event(self.reference, "succeeded", event_id="evt_dup_1")
        r1 = helpers.post_webhook(self.client, event)
        r2 = helpers.post_webhook(self.client, event)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["result"], "duplicate_ignored")
        self.assertEqual(LedgerEntry.objects.filter(event_id="evt_dup_1").count(), 1)
        # creation entry + exactly one webhook entry
        self.assertEqual(LedgerEntry.objects.filter(payment_id=self.payment_id).count(), 2)
        self.assertEqual(self._status(), "succeeded")

    def test_reverse_order_delivery_final_status_correct(self):
        # Final (succeeded) delivered before pending.
        helpers.post_webhook(
            self.client, helpers.make_event(self.reference, "succeeded", event_id="evt_final")
        )
        helpers.post_webhook(
            self.client, helpers.make_event(self.reference, "pending", event_id="evt_pending")
        )
        self.assertEqual(self._status(), "succeeded")

    def test_late_pending_does_not_regress_terminal(self):
        helpers.post_webhook(
            self.client, helpers.make_event(self.reference, "failed", failure_code="card_declined")
        )
        self.assertEqual(self._status(), "failed")
        helpers.post_webhook(self.client, helpers.make_event(self.reference, "pending"))
        self.assertEqual(self._status(), "failed")

    def test_conflicting_terminal_first_wins(self):
        helpers.post_webhook(self.client, helpers.make_event(self.reference, "succeeded"))
        self.assertEqual(self._status(), "succeeded")
        helpers.post_webhook(
            self.client,
            helpers.make_event(self.reference, "failed", failure_code="processor_error"),
        )
        # First terminal wins; a conflicting later terminal does not change status.
        self.assertEqual(self._status(), "succeeded")

    def test_status_derivable_purely_from_ledger(self):
        helpers.post_webhook(self.client, helpers.make_event(self.reference, "succeeded"))
        payment = Payment.objects.get(id=self.payment_id)
        # Cached status matches the fold over the ledger.
        self.assertEqual(payment.status, payment.derive_status())
        self.assertEqual(payment.derive_status(), "succeeded")

    def test_unknown_reference_returns_404(self):
        resp = helpers.post_webhook(
            self.client, helpers.make_event("pr_does_not_exist", "succeeded")
        )
        self.assertEqual(resp.status_code, 404)
