from django.urls import path

from .views import TokenizeView


app_name = "mock_processor"

urlpatterns = [
    path("processor/tokenize", TokenizeView.as_view(), name="tokenize"),
]
