import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac


class EmailVerification(models.Model):
    """Одноразовый код подтверждения почты для ещё не активированного аккаунта.

    Запись существует, пока почта не подтверждена; после успешной проверки
    она удаляется, а пользователь становится активным.
    """
    CODE_LENGTH = 6
    CODE_TTL = timedelta(minutes=10)          # срок действия кода
    RESEND_COOLDOWN = timedelta(seconds=60)   # пауза между повторными отправками
    MAX_ATTEMPTS = 5                          # попыток ввода на один код
    PENDING_TTL = timedelta(hours=1)          # сколько живёт неподтверждённый аккаунт

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='email_verification',
        verbose_name='пользователь',
    )
    # Сам код в базе не хранится — только его HMAC
    code_hash = models.CharField('хеш кода', max_length=64)
    sent_at = models.DateTimeField('отправлен')
    attempts = models.PositiveSmallIntegerField('неудачных попыток', default=0)

    class Meta:
        verbose_name = 'подтверждение почты'
        verbose_name_plural = 'подтверждения почты'

    def __str__(self):
        return f'Код для {self.user}'

    @staticmethod
    def _hash(user_id, code):
        return salted_hmac('accounts.email-code', f'{user_id}:{code}').hexdigest()

    @classmethod
    def issue(cls, user):
        """Создаёт новый код для пользователя (старый перестаёт действовать) и возвращает его."""
        code = ''.join(secrets.choice('0123456789') for _ in range(cls.CODE_LENGTH))
        cls.objects.update_or_create(
            user=user,
            defaults={
                'code_hash': cls._hash(user.pk, code),
                'sent_at': timezone.now(),
                'attempts': 0,
            },
        )
        return code

    @classmethod
    def purge_stale(cls):
        """Удаляет аккаунты, которые так и не подтвердили почту, — освобождает логин и email."""
        from django.contrib.auth import get_user_model
        get_user_model().objects.filter(
            is_active=False,
            email_verification__sent_at__lt=timezone.now() - cls.PENDING_TTL,
        ).delete()

    @property
    def is_expired(self):
        return timezone.now() >= self.sent_at + self.CODE_TTL

    @property
    def attempts_left(self):
        return max(self.MAX_ATTEMPTS - self.attempts, 0)

    @property
    def seconds_until_resend(self):
        remaining = self.sent_at + self.RESEND_COOLDOWN - timezone.now()
        return max(int(remaining.total_seconds()) + 1, 0) if remaining > timedelta(0) else 0

    def check_code(self, code):
        """Проверяет код. Неверная попытка увеличивает счётчик."""
        if self.is_expired or self.attempts_left == 0:
            return False
        if constant_time_compare(self.code_hash, self._hash(self.user_id, code)):
            return True
        type(self).objects.filter(pk=self.pk).update(attempts=F('attempts') + 1)
        self.refresh_from_db(fields=['attempts'])
        return False
