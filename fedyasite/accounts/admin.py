from django.contrib import admin

from .models import EmailVerification


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'sent_at', 'attempts')
    readonly_fields = ('user', 'sent_at', 'attempts')
    exclude = ('code_hash',)

    def has_add_permission(self, request):
        return False
