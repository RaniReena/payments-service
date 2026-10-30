from rest_framework import serializers

from . import state
from .models import LedgerEntry, Payment


class PaymentCreateSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    payment_token = serializers.CharField(max_length=64)

    def validate_currency(self, value):
        value = value.upper()
        if value != "USD":
            raise serializers.ValidationError("Only USD is supported")
        return value


class LedgerEntrySerializer(serializers.ModelSerializer):
    sequence = serializers.IntegerField(source="id", read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            "sequence",
            "event_type",
            "status",
            "failure_code",
            "event_id",
            "occurred_at",
            "created",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    ledger = LedgerEntrySerializer(source="ordered_ledger", many=True, read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "amount_minor",
            "currency",
            "status",
            "method",
            "last4",
            "brand_or_bank_type",
            "processor_reference",
            "created",
            "modified",
            "ledger",
        ]

    def get_status(self, obj) -> str:
        # Derived purely from the ledger (ledger is the source of truth).
        return state.derive_status(list(obj.ordered_ledger()))
