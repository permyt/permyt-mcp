from django.contrib import admin

from app.utils.crypto import hide_token

from .models import Token


class TokenAdmin(admin.ModelAdmin):
    list_display = ("hidden_key", "user", "created", "last_used", "name", "system")
    readonly_fields = ("user", "key", "created", "last_used", "system")
    ordering = ("-created",)

    def hidden_key(self, obj):
        return hide_token(obj.key)


admin.site.register(Token, TokenAdmin)
