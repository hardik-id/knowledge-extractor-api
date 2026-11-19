from django.contrib import admin

from .models import WsTicket


@admin.register(WsTicket)
class WsTicketAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # generic only for stubs
    list_display = ("user", "created_at", "expires_at", "used_at")
    exclude = ("token_hash",)
