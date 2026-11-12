import logging

from django.core.mail import send_mail

from .models import EmailVerification

logger = logging.getLogger(__name__)


def send_verification_code(user):
    """Выпускает новый код и отправляет его на почту. Возвращает True, если письмо ушло."""
    code = EmailVerification.issue(user)
    minutes = int(EmailVerification.CODE_TTL.total_seconds() // 60)
    try:
        send_mail(
            subject=f'{code} — код подтверждения на Барахолке',
            message=(
                f'Здравствуйте, {user.username}!\n\n'
                f'Ваш код подтверждения: {code}\n\n'
                f'Код действует {minutes} минут. '
                'Если вы не регистрировались на Барахолке, просто проигнорируйте это письмо.'
            ),
            from_email=None,  # DEFAULT_FROM_EMAIL
            recipient_list=[user.email],
        )
    except Exception:
        logger.exception('Не удалось отправить код подтверждения на %s', user.email)
        return False
    return True
