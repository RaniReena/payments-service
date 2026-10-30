import datetime

from django.test import SimpleTestCase

from mock_processor import validators


def luhn_card_ending(last4: str, prefix: str = "4") -> str:
    """Return a 16-digit Luhn-valid number ending in ``last4``."""
    fill = 16 - len(prefix) - len(last4)
    for i in range(10**fill):
        candidate = f"{prefix}{i:0{fill}d}{last4}"
        if validators.luhn_valid(candidate):
            return candidate
    raise AssertionError("could not build Luhn number")


class LuhnTests(SimpleTestCase):
    def test_known_valid_card(self):
        self.assertTrue(validators.luhn_valid("4242424242424242"))

    def test_invalid_card(self):
        self.assertFalse(validators.luhn_valid("4242424242424241"))

    def test_non_digits(self):
        self.assertFalse(validators.luhn_valid("abcd"))


class CardValidationTests(SimpleTestCase):
    def test_valid_card(self):
        last4, brand = validators.validate_card("4242424242424242", 12, 2099, "123")
        self.assertEqual(last4, "4242")
        self.assertEqual(brand, "visa")

    def test_invalid_number_raises(self):
        with self.assertRaises(validators.ValidationError) as ctx:
            validators.validate_card("4242424242424241", 12, 2099, "123")
        self.assertEqual(ctx.exception.code, "invalid_number")

    def test_expired_card_raises(self):
        last_year = datetime.date.today().year - 1
        with self.assertRaises(validators.ValidationError) as ctx:
            validators.validate_card("4242424242424242", 1, last_year, "123")
        self.assertEqual(ctx.exception.code, "invalid_expiry")

    def test_bad_cvv_raises(self):
        with self.assertRaises(validators.ValidationError) as ctx:
            validators.validate_card("4242424242424242", 12, 2099, "12")
        self.assertEqual(ctx.exception.code, "invalid_cvv")


class BankValidationTests(SimpleTestCase):
    def test_valid_bank(self):
        last4 = validators.validate_bank("000123456789", "110000000")
        self.assertEqual(last4, "6789")

    def test_bad_routing_length(self):
        with self.assertRaises(validators.ValidationError) as ctx:
            validators.validate_bank("000123456789", "12345")
        self.assertEqual(ctx.exception.code, "invalid_routing")
