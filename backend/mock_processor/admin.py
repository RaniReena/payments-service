from django.contrib import admin

from .models import ProcessorCharge, ProcessorToken


@admin.register(ProcessorToken)
class ProcessorTokenAdmin(admin.ModelAdmin):
    list_display = ("token", "method", "last4", "brand_or_bank_type", "created_at")
    search_fields = ("token",)


@admin.register(ProcessorCharge)
class ProcessorChargeAdmin(admin.ModelAdmin):
    list_display = (
        "processor_reference",
        "method",
        "last4",
        "final_status",
        "failure_code",
        "created_at",
    )
    search_fields = ("processor_reference", "token__token")
