"""True concurrency tests using separate threads and DB connections.

These use ``TransactionTestCase`` (no wrapping transaction) so each thread's
work is really committed and visible across connections. A single-transaction
test would not exercise the row locks and unique constraints that make the
system safe.
"""

import json
import threading

from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse

from mock_processor.models import ProcessorCharge
from payments.models import LedgerEntry, Payment

from . import helpers


class ConcurrentWebhookDeliveryTests(TransactionTestCase):
    reset_sequences = True

    def test_two_concurrent_identical_final_events(self):
        token = helpers.tokenize_card(self.client)
        resp, _ = helpers.create_payment(self.client, token)
        reference = resp.json()["processor_reference"]
        payment_id = resp.json()["id"]

        event = helpers.make_event(reference, "succeeded", event_id="evt_concurrent")
        body = json.dumps(event).encode("utf-8")
        signature = helpers.sign(body)
        url = reverse("payments:processor-webhook")

        results = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()  # fire both at the same instant
            try:
                client = Client()
                response = client.generic(
                    "POST", url, body,
                    content_type="application/json",
                    HTTP_X_PROCESSOR_SIGNATURE=signature,
                )
                results.append(response.json())
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Exactly one ledger entry for this event_id.
        self.assertEqual(LedgerEntry.objects.filter(event_id="evt_concurrent").count(), 1)
        # One correct terminal state.
        self.assertEqual(Payment.objects.get(id=payment_id).status, "succeeded")
        # One request processed it, the other saw it as a duplicate.
        outcomes = sorted(r.get("result") for r in results)
        self.assertEqual(outcomes, ["duplicate_ignored", "processed"])


class ConcurrentPaymentCreationTests(TransactionTestCase):
    reset_sequences = True

    def test_two_concurrent_creates_same_key(self):
        token = helpers.tokenize_card(self.client)
        payload = json.dumps(
            {"amount_minor": 2500, "currency": "USD", "payment_token": token}
        ).encode("utf-8")
        url = reverse("payments:payments")
        key = "idem_concurrent_create"

        results = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            try:
                client = Client()
                response = client.generic(
                    "POST", url, payload,
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=key,
                )
                results.append((response.status_code, response.json()))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Exactly one payment and one processor charge -> no double charge.
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(ProcessorCharge.objects.count(), 1)
        # Both responses reference the same payment.
        ids = {body["id"] for _, body in results}
        self.assertEqual(len(ids), 1)
        statuses = sorted(code for code, _ in results)
        self.assertEqual(statuses, [200, 201])
