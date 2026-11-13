from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import redirect
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from . import services
from .forms import TopUpForm
from .models import Order


class WalletView(LoginRequiredMixin, ListView):
    """Баланс, форма тестового пополнения и история операций."""
    template_name = 'wallet/wallet.html'
    context_object_name = 'transactions'
    paginate_by = 20

    def get_queryset(self):
        self.wallet = services.get_wallet(self.request.user)
        services.expire_overdue(Order.objects.filter(buyer=self.request.user))
        self.wallet.refresh_from_db()
        return self.wallet.transactions.select_related('order')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['wallet'] = self.wallet
        context['quick_amounts'] = [1000, 5000, 10000, 50000]
        context['topup_max'] = services.TOPUP_MAX
        # ?amount=… — подставить сумму в поле (например, недостающую для брони)
        prefill = TopUpForm({'amount': self.request.GET.get('amount', '')})
        context['prefill_amount'] = prefill.cleaned_data['amount'] if prefill.is_valid() else ''
        return context


class TopUpView(LoginRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request):
        form = TopUpForm(request.POST)
        if form.is_valid():
            try:
                services.top_up(request.user, form.cleaned_data['amount'])
            except services.WalletError as e:
                messages.error(request, str(e))
            else:
                amount = floatformat(form.cleaned_data['amount'], '-2g')
                messages.success(request, f'Баланс пополнен на {amount} ₽.')
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
        return redirect('wallet:wallet')


class OrderListView(LoginRequiredMixin, ListView):
    """Мои покупки (?tab=purchases) и продажи (?tab=sales)."""
    template_name = 'wallet/orders.html'
    context_object_name = 'orders'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        services.expire_overdue(Order.objects.filter(Q(buyer=user) | Q(seller=user)))
        self.tab = 'sales' if self.request.GET.get('tab') == 'sales' else 'purchases'
        if self.tab == 'sales':
            return user.sales.select_related('buyer', 'ad')
        return user.purchases.select_related('seller', 'ad')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tab'] = self.tab
        context['querystring'] = f'tab={self.tab}'
        return context


class _OrderActionView(LoginRequiredMixin, View):
    http_method_names = ['post']
    action = None
    success_message = ''

    def post(self, request, pk):
        try:
            order = self.action(pk, request.user)
        except services.WalletError as e:
            messages.error(request, str(e))
            return redirect('wallet:orders')
        messages.success(request, self.success_message)
        next_url = request.POST.get('next', '')
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        tab ='sales' if order.seller_id == request.user.pk else 'purchases'
        return redirect(f"{reverse('wallet:orders')}?tab={tab}")


class OrderCompleteView(_OrderActionView):
    action = staticmethod(services.complete)
    success_message = 'Получение подтверждено, деньги переведены продавцу.'


class OrderCancelView(_OrderActionView):
    action = staticmethod(services.cancel)
    success_message = 'Бронь снята, деньги возвращены покупателю.'


class ReserveView(LoginRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        try:
            services.reserve(pk, request.user)
        except services.WalletError as e:
            messages.error(request, str(e))
            return redirect('ads:detail', pk=pk)
        messages.success(
            request,
            f'Объявление забронировано на {services.RESERVATION_HOURS} ч. '
            'Подтвердите получение товара, когда встретитесь с продавцом.',
        )
        return redirect('wallet:orders')
