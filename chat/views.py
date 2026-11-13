from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import ListView

from ads.models import Ad

from . import services
from .forms import MessageForm
from .models import Conversation, Message


def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _parse_id(value):
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


class InboxView(LoginRequiredMixin, ListView):
    """Список диалогов пользователя — и как покупателя, и как продавца."""
    template_name = 'chat/inbox.html'
    context_object_name = 'conversations'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        last = Message.objects.filter(conversation=OuterRef('pk')).order_by('-created_at', '-pk')
        unread = (
            Message.objects.filter(conversation=OuterRef('pk'), is_read=False)
            .exclude(sender=user)
            .order_by().values('conversation')
            .annotate(c=Count('pk')).values('c')
        )
        queryset = (
            Conversation.for_user(user)
            .select_related('ad', 'buyer', 'seller')
            .annotate(
                unread=Coalesce(Subquery(unread, output_field=IntegerField()), Value(0)),
                last_text=Subquery(last.values('text')[:1]),
                last_sender_id=Subquery(last.values('sender_id')[:1]),
                last_is_read=Subquery(last.values('is_read')[:1]),
            )
        )
        # ?ad=<pk> — диалоги по одному своему объявлению
        self.ad = None
        ad_id = _parse_id(self.request.GET.get('ad'))
        if ad_id:
            self.ad = Ad.objects.filter(pk=ad_id, author=user).first()
            if self.ad:
                queryset = queryset.filter(ad=self.ad)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        for conv in context['conversations']:
            is_seller = conv.seller_id == user.pk
            conv.companion = conv.buyer if is_seller else conv.seller
            conv.role = 'покупатель' if is_seller else 'продавец'
        context['filter_ad'] = self.ad
        context['querystring'] = f'ad={self.ad.pk}' if self.ad else ''
        return context


class ConversationView(LoginRequiredMixin, View):
    """Страница переписки: история сообщений и форма ответа."""
    template_name = 'chat/conversation.html'

    def get_conversation(self, pk):
        return get_object_or_404(
            Conversation.for_user(self.request.user).select_related('ad', 'buyer', 'seller'),
            pk=pk,
        )

    def render_page(self, conversation, form):
        user = self.request.user
        services.mark_read(conversation, user)
        chat_messages = list(conversation.messages.all())
        return render(self.request, self.template_name, {
            'conversation': conversation,
            'ad': conversation.ad,
            'companion': conversation.other_user(user),
            'chat_messages': chat_messages,
            'last_id': chat_messages[-1].pk if chat_messages else 0,
            'read_upto': services.last_read_own_id(conversation, user),
            'form': form,
        })

    def get(self, request, pk):
        return self.render_page(self.get_conversation(pk), MessageForm())

    def post(self, request, pk):
        conversation = self.get_conversation(pk)
        form = MessageForm(request.POST)
        if form.is_valid():
            try:
                services.send_message(conversation, request.user, form.cleaned_data['text'])
            except services.ChatError as e:
                form.add_error('text', str(e))
        if form.errors:
            if _is_ajax(request):
                return JsonResponse({'error': ' '.join(form.errors['text'])}, status=400)
            return self.render_page(conversation, form)
        if _is_ajax(request):
            return updates_response(request, conversation, _parse_id(request.POST.get('after')))
        return redirect(f'{conversation.get_absolute_url()}#chat-form')


class ConversationUpdatesView(LoginRequiredMixin, View):
    """Новые сообщения после ?after=<id> — для автообновления без перезагрузки."""
    http_method_names = ['get']

    def get(self, request, pk):
        conversation = get_object_or_404(Conversation.for_user(request.user), pk=pk)
        return updates_response(request, conversation, _parse_id(request.GET.get('after')))


def updates_response(request, conversation, after):
    user = request.user
    new_messages = list(conversation.messages.filter(pk__gt=after))
    if new_messages:
        # Отмечаем прочитанными только те входящие, что действительно показали
        services.mark_read(conversation, user, up_to_id=new_messages[-1].pk)
    read_upto = services.last_read_own_id(conversation, user)
    html = render_to_string(
        'chat/_messages.html',
        {'chat_messages': new_messages, 'read_upto': read_upto, 'user': user},
    )
    return JsonResponse({
        'html': html,
        'last_id': new_messages[-1].pk if new_messages else after,
        'read_upto': read_upto,
        'unread_total': services.unread_messages(user).count(),
    })


class ConversationStartView(LoginRequiredMixin, View):
    """«Написать продавцу»: диалог создаётся только с первым сообщением."""
    template_name = 'chat/conversation.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.ad = get_object_or_404(Ad.objects.select_related('author'), pk=kwargs['pk'])
        if self.ad.author_id == request.user.pk:
            messages.error(request, 'Это ваше объявление — написать самому себе нельзя.')
            return redirect(self.ad)
        existing = Conversation.objects.filter(ad=self.ad, buyer=request.user).first()
        if existing and request.method == 'GET':
            return redirect(existing)
        if not existing and not self.ad.is_active:
            messages.error(request, 'Объявление снято с публикации — написать продавцу нельзя.')
            return redirect('ads:list')
        return super().dispatch(request, *args, **kwargs)

    def render_page(self, form):
        return render(self.request, self.template_name, {
            'conversation': None,
            'ad': self.ad,
            'companion': self.ad.author,
            'chat_messages': [],
            'last_id': 0,
            'read_upto': 0,
            'form': form,
        })

    def get(self, request, pk):
        return self.render_page(MessageForm())

    def post(self, request, pk):
        form = MessageForm(request.POST)
        if form.is_valid():
            existing = Conversation.objects.filter(ad=self.ad, buyer=request.user).first()
            try:
                if existing:
                    services.send_message(existing, request.user, form.cleaned_data['text'])
                    conversation = existing
                else:
                    conversation = services.start_conversation(
                        self.ad, request.user, form.cleaned_data['text'],
                    )
            except services.ChatError as e:
                form.add_error('text', str(e))
            else:
                return redirect(f'{conversation.get_absolute_url()}#chat-form')
        return self.render_page(form)
