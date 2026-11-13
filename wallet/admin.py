from django.contrib import admin, messages

from . import services
from .models import Order, Transaction, Wallet


class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 0
    can_delete = False
    fields = ('created_at', 'kind', 'amount', 'order', 'comment')
    readonly_fields = fields
    ordering = ('-created_at', '-pk')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """Суммы только для чтения: менять баланс можно лишь действиями, которые пишут журнал."""
    list_display = ('user', 'balance', 'held')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'balance', 'held')
    inlines = [TransactionInline]
    actions = ['add_10000', 'add_50000']

    def has_add_permission(self, request):
        return False

    def _add(self, request, queryset, amount):
        done = 0
        for wallet in queryset.select_related('user'):
            try:
                services.top_up(wallet.user, amount, comment=f'Начислено администратором {request.user}')
                done += 1
            except services.WalletError as e:
                self.message_user(request, f'{wallet.user}: {e}', messages.WARNING)
        if done:
            self.message_user(request, f'Начислено {amount} ₽ на {done} кошел.', messages.SUCCESS)

    @admin.action(description='Начислить 10 000 ₽')
    def add_10000(self, request, queryset):
        self._add(request, queryset, 10_000)

    @admin.action(description='Начислить 50 000 ₽')
    def add_50000(self, request, queryset):
        self._add(request, queryset, 50_000)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('pk', 'ad_title', 'buyer', 'seller', 'amount', 'status', 'created_at', 'expires_at')
    list_filter = ('status',)
    search_fields = ('ad_title', 'buyer__username', 'seller__username')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Только просмотр: ручная смена статуса разошлась бы с балансами
        return False


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'wallet', 'kind', 'amount', 'order', 'comment')
    list_filter = ('kind',)
    search_fields = ('wallet__user__username', 'comment')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
