"""Django admin for aa-fuelalert."""

from django.contrib import admin

from .models import AlertLog, Recipient


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    """Recipients; the phone number is masked in the list."""

    list_display = ("user", "channel", "contact_display", "enabled", "updated_at")
    list_filter = ("channel", "enabled")
    search_fields = ("user__username", "user__profile__main_character__character_name")
    filter_horizontal = ("corporations",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    """Sent alerts (read-only). Deleting an entry lets that alert fire again."""

    list_display = ("structure_id", "key", "fuel_expires", "sent_at")
    list_filter = ("key",)
    search_fields = ("structure_id",)

    def has_add_permission(self, request):
        """Entries are only created by the fuel check task."""
        return False

    def has_change_permission(self, request, obj=None):
        """Entries are read-only."""
        return False
