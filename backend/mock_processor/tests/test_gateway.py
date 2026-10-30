from django.test import TestCase

from mock_processor import gateway, outcomes
from mock_processor.models import ProcessorToken


class OutcomeMatrixTests(TestCase):
    def test_card_outcomes(self):
        self.assertEqual(outcomes.outcome_for("card", "0002"),
                         outcomes.Outcome("failed", "card_declined", 0))
        self.assertEqual(outcomes.outcome_for("card", "0119"),
                         outcomes.Outcome("failed", "processor_error", 0))
        self.assertEqual(outcomes.outcome_for("card", "0341"),
                         outcomes.Outcome("succeeded", None, 15))
        self.assertEqual(outcomes.outcome_for("card", "9999"),
                         outcomes.Outcome("succeeded", None, 0))

    def test_bank_outcomes(self):
        self.assertEqual(outcomes.outcome_for("bank", "0002"),
                         outcomes.Outcome("failed", "insufficient_funds", 0))
        self.assertEqual(outcomes.outcome_for("bank", "0119"),
                         outcomes.Outcome("failed", "processor_error", 0))


class GatewayChargeTests(TestCase):
    def _token(self, method="card", last4="4242"):
        return ProcessorToken.objects.create(
            token="tok_" + last4, method=method, last4=last4, brand_or_bank_type="visa"
        )

    def test_charge_accepts_as_pending_and_records_outcome(self):
        self._token(last4="0002")
        result = gateway.charge("tok_0002", 1000, "USD")
        self.assertEqual(result.status, "pending")
        self.assertTrue(result.processor_reference.startswith("pr_"))

        status = gateway.get_charge_status(result.processor_reference)
        self.assertEqual(status.status, "failed")
        self.assertEqual(status.failure_code, "card_declined")

    def test_charge_unknown_token_raises(self):
        with self.assertRaises(gateway.ProcessorError):
            gateway.charge("tok_missing", 1000, "USD")
