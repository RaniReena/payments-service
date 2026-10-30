from django.contrib import admin

from .models import LedgerEntry, Payment


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False
    readonly_fields = ("event_type", "status", "failure_code", "event_id", "occurred_at", "created")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "amount_minor", "currency", "status", "method", "last4", "created")
    list_filter = ("status", "method", "currency")
    search_fields = ("id", "processor_reference", "idempotency_key")
    readonly_fields = ("id", "processor_reference", "created", "modified")
    inlines = [LedgerEntryInline]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "event_type", "status", "failure_code", "event_id", "created")
    list_filter = ("event_type", "status")
    search_fields = ("payment__id", "event_id")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
