from django.contrib import admin

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ('created_at', 'sender', 'text', 'is_read')
    readonly_fields = ('created_at', 'sender')
    ordering = ('created_at', 'pk')


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'ad_title', 'buyer', 'seller', 'updated_at')
    search_fields = ('ad_title', 'buyer__username', 'seller__username')
    readonly_fields = ('ad', 'ad_title', 'buyer', 'seller', 'created_at', 'updated_at')
    inlines = [MessageInline]

    def has_add_permission(self, request):
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'conversation', 'sender', 'short_text', 'is_read')
    list_filter = ('is_read',)
    search_fields = ('text', 'sender__username')
    raw_id_fields = ('conversation', 'sender')

    @admin.display(description='текст')
    def short_text(self, obj):
        return obj.text[:60]

    def has_add_permission(self, request):
        return False
