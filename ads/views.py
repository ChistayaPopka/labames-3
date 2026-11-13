from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Exists, F, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import (
    CreateView, DeleteView, DetailView, ListView, UpdateView,
)

from wallet import services as wallet_services
from wallet.models import Order, Wallet

from .forms import AdFilterForm, AdForm
from .models import Ad


class AdListView(ListView):
    """Главная: лента активных объявлений с поиском и фильтрами."""
    model = Ad
    paginate_by = 9
    context_object_name = 'ads'

    def get_queryset(self):
        self.filter_form = AdFilterForm(self.request.GET or None)
        # Забронированные объявления остаются в ленте, но карточка показывается приглушённой
        queryset = (
            Ad.objects.filter(is_active=True)
            .annotate(is_reserved=wallet_services.ad_is_reserved())
            .select_related('category', 'author')
        )
        if self.filter_form.is_bound:
            queryset = self.filter_form.filter(queryset)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = self.filter_form
        # Параметры фильтра без page — для ссылок пагинации
        params = self.request.GET.copy()
        params.pop('page', None)
        context['querystring'] = params.urlencode()
        if self.request.user.is_authenticated:
            context['favorite_ids'] = set(
                self.request.user.favorite_ads.values_list('pk', flat=True)
            )
        return context


class AdDetailView(DetailView):
    model = Ad
    context_object_name = 'ad'

    def get_queryset(self):
        queryset = Ad.objects.select_related('category', 'author')
        user = self.request.user
        # Снятые с публикации объявления видит только автор
        if user.is_authenticated:
            return queryset.filter(Q(is_active=True) | Q(author=user))
        return queryset.filter(is_active=True)

    def get_object(self, queryset=None):
        ad = super().get_object(queryset)
        if ad.author != self.request.user:
            Ad.objects.filter(pk=ad.pk).update(views=F('views') + 1)
            ad.views += 1
        return ad

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['favorite_ids'] = (
            set(user.favorite_ads.values_list('pk', flat=True))
            if user.is_authenticated else set()
        )
        context['is_favorite'] = self.object.pk in context['favorite_ids']
        context['similar_ads'] = (
            Ad.objects.filter(is_active=True, category=self.object.category)
            .annotate(is_reserved=wallet_services.ad_is_reserved())
            .exclude(pk=self.object.pk)
            .select_related('category')[:3]
        )

        # Бронь: сначала закрываем просроченную, если есть, потом ищем активную
        wallet_services.expire_overdue(Order.objects.filter(ad=self.object))
        context['active_order'] = (
            wallet_services.active_reservations()
            .filter(ad=self.object).select_related('buyer').first()
        )
        context['reservation_hours'] = wallet_services.RESERVATION_HOURS
        if user.is_authenticated:
            if self.object.author_id == user.pk:
                context['conversations_count'] = self.object.conversations.count()
            else:
                context['conversation'] = self.object.conversations.filter(buyer=user).first()
            balance = (
                Wallet.objects.filter(user=user).values_list('balance', flat=True).first() or 0
            )
            context['missing_amount'] = max(self.object.price - balance, 0)
        return context


class AuthorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Пускает только автора объявления."""
    raise_exception = False

    def test_func(self):
        return self.get_object().author == self.request.user

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, 'Редактировать объявление может только его автор.')
            return redirect('ads:list')
        return super().handle_no_permission()


class AdCreateView(LoginRequiredMixin, CreateView):
    model = Ad
    form_class = AdForm

    def form_valid(self, form):
        form.instance.author = self.request.user
        messages.success(self.request, 'Объявление опубликовано.')
        return super().form_valid(form)


class AdUpdateView(AuthorRequiredMixin, UpdateView):
    model = Ad
    form_class = AdForm

    def form_valid(self, form):
        messages.success(self.request, 'Изменения сохранены.')
        return super().form_valid(form)


class AdDeleteView(AuthorRequiredMixin, DeleteView):
    model = Ad
    success_url = reverse_lazy('ads:my')

    def form_valid(self, form):
        if wallet_services.active_reservations().filter(ad=self.object).exists():
            messages.error(
                self.request,
                'Объявление забронировано — его нельзя удалить. Сначала отмените бронь в разделе «Заказы».',
            )
            return redirect(self.object)
        messages.success(self.request, 'Объявление удалено.')
        return super().form_valid(form)


class MyAdsView(LoginRequiredMixin, ListView):
    template_name = 'ads/my_ads.html'
    context_object_name = 'ads'
    paginate_by = 10

    def get_queryset(self):
        return self.request.user.ads.select_related('category').annotate(
            is_reserved=wallet_services.ad_is_reserved(),
            is_sold=Exists(Order.objects.filter(ad=OuterRef('pk'), status=Order.Status.COMPLETED)),
        )


class FavoriteListView(LoginRequiredMixin, ListView):
    template_name = 'ads/favorites.html'
    context_object_name = 'ads'
    paginate_by = 9

    def get_queryset(self):
        return (
            self.request.user.favorite_ads.filter(is_active=True)
            .annotate(is_reserved=wallet_services.ad_is_reserved())
            .select_related('category', 'author')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['favorite_ids'] = {ad.pk for ad in context['ads']}
        return context


class FavoriteToggleView(LoginRequiredMixin, View):
    """Добавляет объявление в избранное или убирает из него (только POST)."""
    http_method_names = ['post']

    def post(self, request, pk):
        ad = get_object_or_404(Ad, pk=pk, is_active=True)
        if ad.favorited_by.filter(pk=request.user.pk).exists():
            ad.favorited_by.remove(request.user)
        else:
            ad.favorited_by.add(request.user)
        next_url = request.POST.get('next', '')
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect(ad)
