from django.urls import path

from .views import (
    PaymentDetailView,
    PaymentReplayView,
    PaymentsView,
    ProcessorWebhookView,
)


app_name = "payments"

urlpatterns = [
    path("api/payments", PaymentsView.as_view(), name="payments"),
    path("api/payments/<uuid:pk>", PaymentDetailView.as_view(), name="payment-detail"),
    path("api/payments/<uuid:pk>/replay", PaymentReplayView.as_view(), name="payment-replay"),
    path("webhooks/processor", ProcessorWebhookView.as_view(), name="processor-webhook"),
]
