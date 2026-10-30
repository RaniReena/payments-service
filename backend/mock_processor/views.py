"""Processor HTTP surface.

Only ``POST /processor/tokenize`` is exposed over HTTP. Charging is done via the
in-process :mod:`mock_processor.gateway`. The client/frontend calls tokenize
directly so that raw card/bank data never reaches the payments app.
"""

from __future__ import annotations

import secrets

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import validators
from .models import ProcessorToken
from .serializers import TokenizeRequestSerializer, TokenizeResponseSerializer


class TokenizeView(APIView):
    """Validate raw instrument data and return a non-sensitive token."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=TokenizeRequestSerializer,
        responses={201: TokenizeResponseSerializer},
    )
    def post(self, request):
        serializer = TokenizeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        method = data["method"]

        try:
            if method == "card":
                last4, brand_or_bank_type = validators.validate_card(
                    data["number"], data["exp_month"], data["exp_year"], data["cvv"]
                )
            else:
                last4 = validators.validate_bank(data["account_number"], data["routing_number"])
                brand_or_bank_type = data.get("bank_type", "checking")
        except validators.ValidationError as exc:
            return Response({"error": exc.code}, status=status.HTTP_400_BAD_REQUEST)

        token_value = "tok_" + secrets.token_hex(16)
        ProcessorToken.objects.create(
            token=token_value,
            method=method,
            last4=last4,
            brand_or_bank_type=brand_or_bank_type,
        )
        body = {
            "token": token_value,
            "method": method,
            "last4": last4,
            "brand_or_bank_type": brand_or_bank_type,
        }
        return Response(body, status=status.HTTP_201_CREATED)
