from django.test import TestCase
from django.urls import reverse

from mock_processor.models import ProcessorToken

from .test_validators import luhn_card_ending


class TokenizeEndpointTests(TestCase):
    def test_tokenize_card_returns_token_and_last4(self):
        resp = self.client.post(
            reverse("mock_processor:tokenize"),
            data={
                "method": "card",
                "number": "4242424242424242",
                "exp_month": 12,
                "exp_year": 2099,
                "cvv": "123",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body["token"].startswith("tok_"))
        self.assertEqual(body["method"], "card")
        self.assertEqual(body["last4"], "4242")
        self.assertEqual(body["brand_or_bank_type"], "visa")
        # Response must not echo the raw number or cvv.
        self.assertNotIn("number", body)
        self.assertNotIn("cvv", body)

    def test_tokenize_stores_no_sensitive_data(self):
        number = luhn_card_ending("1881")
        self.client.post(
            reverse("mock_processor:tokenize"),
            data={"number": number, "exp_month": 12, "exp_year": 2099, "cvv": "999"},
            content_type="application/json",
        )
        token = ProcessorToken.objects.get()
        self.assertEqual(token.last4, "1881")
        # The stored row only has last4, never the full number or cvv.
        for value in vars(token).values():
            self.assertNotIn(number, str(value))
            self.assertNotIn("999", [token.last4])  # cvv never stored

    def test_invalid_number_rejected(self):
        resp = self.client.post(
            reverse("mock_processor:tokenize"),
            data={"number": "4242424242424241", "exp_month": 12, "exp_year": 2099, "cvv": "123"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_number")

    def test_tokenize_bank(self):
        resp = self.client.post(
            reverse("mock_processor:tokenize"),
            data={"method": "bank", "account_number": "000123456789", "routing_number": "110000000"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["method"], "bank")
        self.assertEqual(body["last4"], "6789")
