"""Request/response shapes for the tokenize endpoint.

Raw instrument fields are write-only. They are validated and immediately
discarded — never echoed back, stored, or logged.
"""

from rest_framework import serializers


class TokenizeRequestSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=["card", "bank"], required=False)

    # Card fields
    number = serializers.CharField(required=False, write_only=True, trim_whitespace=True)
    exp_month = serializers.IntegerField(required=False, write_only=True)
    exp_year = serializers.IntegerField(required=False, write_only=True)
    cvv = serializers.CharField(required=False, write_only=True)

    # Bank fields
    account_number = serializers.CharField(required=False, write_only=True)
    routing_number = serializers.CharField(required=False, write_only=True)
    bank_type = serializers.ChoiceField(
        choices=["checking", "savings"], required=False, default="checking"
    )

    def validate(self, attrs):
        method = attrs.get("method")
        if not method:
            method = (
                "card" if attrs.get("number") else "bank" if attrs.get("account_number") else None
            )
        if method == "card":
            missing = [f for f in ("number", "exp_month", "exp_year", "cvv") if not attrs.get(f)]
            if missing:
                raise serializers.ValidationError({"error": "invalid_request", "missing": missing})
        elif method == "bank":
            missing = [f for f in ("account_number", "routing_number") if not attrs.get(f)]
            if missing:
                raise serializers.ValidationError({"error": "invalid_request", "missing": missing})
        else:
            raise serializers.ValidationError(
                {"error": "invalid_request", "detail": "Provide card or bank details"}
            )
        attrs["method"] = method
        return attrs


class TokenizeResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    method = serializers.CharField()
    last4 = serializers.CharField()
    brand_or_bank_type = serializers.CharField()
