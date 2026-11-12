from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, FormView

from .emails import send_verification_code
from .forms import SignUpForm, VerificationCodeForm
from .models import EmailVerification

User = get_user_model()

# В сессии хранится id аккаунта, который ждёт подтверждения почты
PENDING_SESSION_KEY = 'pending_user_id'
AUTH_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def start_verification(request, user):
    """Отправляет код и запоминает в сессии, чей аккаунт подтверждаем."""
    request.session[PENDING_SESSION_KEY] = user.pk
    verification = EmailVerification.objects.filter(user=user).first()
    # Не шлём новое письмо, если предыдущий код только что отправлен
    if verification and not verification.is_expired and verification.seconds_until_resend:
        return
    if not send_verification_code(user):
        messages.error(
            request,
            'Не удалось отправить письмо с кодом. Попробуйте запросить код ещё раз чуть позже.',
        )


def get_pending_user(request):
    user_id = request.session.get(PENDING_SESSION_KEY)
    if not user_id:
        return None
    return (
        User.objects.filter(pk=user_id, is_active=False, email_verification__isnull=False)
        .select_related('email_verification')
        .first()
    )


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = 'registration/signup.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('ads:list')
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        # Освобождаем логины и почты брошенных регистраций
        EmailVerification.purge_stale()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save()
        start_verification(self.request, self.object)
        return redirect('verify_email')


class LoginView(auth_views.LoginView):
    """Обычный вход; неподтверждённый аккаунт отправляем вводить код."""

    def form_invalid(self, form):
        username = form.data.get('username', '')
        password = form.data.get('password', '')
        user = User.objects.filter(
            username=username, is_active=False, email_verification__isnull=False,
        ).first()
        if user and user.check_password(password):
            start_verification(self.request, user)
            messages.info(self.request, 'Сначала подтвердите почту — мы отправили вам код.')
            return redirect('verify_email')
        return super().form_invalid(form)


class VerifyEmailView(FormView):
    form_class = VerificationCodeForm
    template_name = 'registration/verify_email.html'
    success_url = reverse_lazy('ads:list')

    def dispatch(self, request, *args, **kwargs):
        self.pending_user = get_pending_user(request)
        if self.pending_user is None:
            request.session.pop(PENDING_SESSION_KEY, None)
            messages.info(request, 'Нет регистрации, ожидающей подтверждения. Зарегистрируйтесь или войдите.')
            return redirect('signup')
        self.verification = self.pending_user.email_verification
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        verification = self.verification
        if verification.is_expired:
            form.add_error('code', 'Срок действия кода истёк. Запросите новый код.')
            return self.form_invalid(form)
        if verification.attempts_left == 0:
            form.add_error('code', 'Слишком много неверных попыток. Запросите новый код.')
            return self.form_invalid(form)
        if not verification.check_code(form.cleaned_data['code']):
            if verification.attempts_left:
                error = f'Неверный код. Осталось попыток: {verification.attempts_left}.'
            else:
                error = 'Неверный код. Попытки закончились — запросите новый код.'
            form.add_error('code', error)
            return self.form_invalid(form)

        user = self.pending_user
        user.is_active = True
        user.save(update_fields=['is_active'])
        verification.delete()
        self.request.session.pop(PENDING_SESSION_KEY, None)
        login(self.request, user, backend=AUTH_BACKEND)
        messages.success(self.request, 'Почта подтверждена. Добро пожаловать!')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['email'] = self.pending_user.email
        context['ttl_minutes'] = int(EmailVerification.CODE_TTL.total_seconds() // 60)
        context['resend_wait'] = self.verification.seconds_until_resend
        return context


class ResendCodeView(View):
    http_method_names = ['post']

    def post(self, request):
        user = get_pending_user(request)
        if user is None:
            return redirect('signup')
        wait = user.email_verification.seconds_until_resend
        if wait:
            messages.warning(request, f'Новый код можно запросить через {wait} с.')
        elif send_verification_code(user):
            messages.success(request, 'Новый код отправлен. Предыдущий больше не действует.')
        else:
            messages.error(request, 'Не удалось отправить письмо. Попробуйте позже.')
        return redirect('verify_email')
