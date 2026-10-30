"""HTTP surface for payments and the processor webhook."""

from __future__ import annotations

import json

from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import OpenApiParameter, extend_schema

from . import services, signing, state
from .models import Payment
from .serializers import PaymentCreateSerializer, PaymentSerializer


ALLOWED_EVENT_STATUSES = set(state.ALL_STATUSES)


class PaymentsView(APIView):
    """``POST /api/payments`` to create; ``GET /api/payments`` to list."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=PaymentCreateSerializer,
        responses={201: PaymentSerializer},
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=True,
                type=str,
            )
        ],
    )
    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"error": "missing_idempotency_key", "detail": "Idempotency-Key header required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment, created, body = services.create_payment(
                amount_minor=data["amount_minor"],
                currency=data["currency"],
                payment_token=data["payment_token"],
                idempotency_key=idempotency_key,
            )
        except services.IdempotencyConflict:
            return Response(
                {
                    "error": "idempotency_key_reuse",
                    "detail": "Idempotency-Key already used with a different request body",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except services.ProcessorError as exc:
            return Response(
                {"error": "processor_error", "detail": exc.code},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(body, status=http_status)

    def get(self, request):
        payments = Payment.objects.all().order_by("-created").prefetch_related("ledger_entries")
        return Response(PaymentSerializer(payments, many=True).data)


class PaymentDetailView(APIView):
    """``GET /api/payments/{id}`` -> current status and ledger history."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: PaymentSerializer})
    def get(self, request, pk):
        try:
            payment = Payment.objects.prefetch_related("ledger_entries").get(pk=pk)
        except Payment.DoesNotExist:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(PaymentSerializer(payment).data)


class PaymentReplayView(APIView):
    """``POST /api/payments/{id}/replay`` -> admin-only safe replay."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            result = services.replay_payment(pk)
        except services.PaymentNotFound:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(result, status=status.HTTP_200_OK)


class ProcessorWebhookView(APIView):
    """``POST /webhooks/processor`` -> verify signature and apply the event."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw_body = request.body
        provided = request.headers.get("X-Processor-Signature")
        if not signing.is_valid_signature(raw_body, provided):
            # Reject without touching any state.
            return Response(
                {"error": "invalid_signature"}, status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            event = json.loads(raw_body)
        except (ValueError, TypeError):
            return Response({"error": "invalid_json"}, status=status.HTTP_400_BAD_REQUEST)

        required = {"event_id", "processor_reference", "status"}
        if not isinstance(event, dict) or not required.issubset(event):
            return Response({"error": "invalid_payload"}, status=status.HTTP_400_BAD_REQUEST)
        if event["status"] not in ALLOWED_EVENT_STATUSES:
            return Response({"error": "invalid_status"}, status=status.HTTP_400_BAD_REQUEST)

        result = services.process_webhook_event(event)
        if result["result"] == "unknown_reference":
            return Response({"error": "unknown_reference"}, status=status.HTTP_404_NOT_FOUND)
        return Response(result, status=status.HTTP_200_OK)
