from django.db import DatabaseError, transaction
from django.test import TestCase

from payments.models import LedgerEntry

from . import helpers


class AppendOnlyLedgerTests(TestCase):
    def setUp(self):
        token = helpers.tokenize_card(self.client)
        resp, _ = helpers.create_payment(self.client, token)
        self.entry = LedgerEntry.objects.get(payment_id=resp.json()["id"])

    def test_db_trigger_blocks_update(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                LedgerEntry.objects.filter(pk=self.entry.pk).update(status="failed")

    def test_db_trigger_blocks_delete(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                LedgerEntry.objects.filter(pk=self.entry.pk).delete()
        self.assertTrue(LedgerEntry.objects.filter(pk=self.entry.pk).exists())

    def test_model_guard_blocks_save_update(self):
        self.entry.status = "failed"
        with self.assertRaises(ValueError):
            self.entry.save()

    def test_model_guard_blocks_delete(self):
        with self.assertRaises(ValueError):
            self.entry.delete()
