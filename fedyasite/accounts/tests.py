import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import EmailVerification

User = get_user_model()

PASSWORD = 'S3cure-pass-xyz'


class SignUpFlowTestCase(TestCase):
    def signup(self, username='newbie', email='newbie@example.com'):
        return self.client.post(reverse('signup'), {
            'username': username, 'email': email,
            'password1': PASSWORD, 'password2': PASSWORD,
        })

    def last_code(self):
        return re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)

    def wrong_code(self):
        return '000000' if self.last_code() != '000000' else '111111'

    def verify(self, code):
        return self.client.post(reverse('verify_email'), {'code': code})

    def age_code(self, delta):
        EmailVerification.objects.update(sent_at=timezone.now() - delta)

    def is_logged_in(self):
        return '_auth_user_id' in self.client.session


class SignUpTests(SignUpFlowTestCase):
    def test_signup_creates_inactive_user_and_sends_code(self):
        response = self.signup()
        self.assertRedirects(response, reverse('verify_email'))
        user = User.objects.get(username='newbie')
        self.assertFalse(user.is_active)
        self.assertFalse(self.is_logged_in())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['newbie@example.com'])
        # Код в базе в открытом виде не хранится
        self.assertNotIn(self.last_code(), user.email_verification.code_hash)

    def test_correct_code_activates_and_logs_in(self):
        self.signup()
        response = self.verify(self.last_code())
        self.assertRedirects(response, reverse('ads:list'))
        user = User.objects.get(username='newbie')
        self.assertTrue(user.is_active)
        self.assertTrue(self.is_logged_in())
        self.assertFalse(EmailVerification.objects.exists())

    def test_code_is_single_use(self):
        self.signup()
        code = self.last_code()
        self.verify(code)
        self.client.logout()
        # Повторно использовать код нельзя: подтверждать уже нечего
        self.assertRedirects(self.verify(code), reverse('signup'))
        self.assertFalse(self.is_logged_in())

    def test_wrong_code_rejected_and_attempts_limited(self):
        self.signup()
        for _ in range(EmailVerification.MAX_ATTEMPTS):
            response = self.verify(self.wrong_code())
            self.assertEqual(response.status_code, 200)
        # Попытки исчерпаны — даже верный код больше не принимается
        response = self.verify(self.last_code())
        self.assertContains(response, 'Слишком много неверных попыток')
        self.assertFalse(User.objects.get(username='newbie').is_active)

    def test_expired_code_rejected(self):
        self.signup()
        self.age_code(EmailVerification.CODE_TTL + timedelta(seconds=1))
        response = self.verify(self.last_code())
        self.assertContains(response, 'Срок действия кода истёк')
        self.assertFalse(User.objects.get(username='newbie').is_active)

    def test_non_digit_code_rejected(self):
        self.signup()
        response = self.verify('abcdef')
        self.assertContains(response, 'Код состоит только из цифр')
        self.assertEqual(EmailVerification.objects.get().attempts, 0)

    def test_email_required_and_unique(self):
        self.assertEqual(self.signup(email='').status_code, 200)
        self.assertFalse(User.objects.exists())
        User.objects.create_user('first', email='taken@example.com', password=PASSWORD)
        response = self.signup(email='Taken@Example.com')
        self.assertContains(response, 'уже зарегистрирован')
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_verify_page_without_pending_registration(self):
        self.assertRedirects(self.client.get(reverse('verify_email')), reverse('signup'))

    def test_stale_unverified_account_frees_username_and_email(self):
        self.signup()
        self.age_code(EmailVerification.PENDING_TTL + timedelta(seconds=1))
        self.client.session.flush()
        response = self.signup()
        self.assertRedirects(response, reverse('verify_email'))
        self.assertEqual(User.objects.filter(username='newbie').count(), 1)

    def test_mail_failure_keeps_account_and_allows_resend(self):
        with mock.patch('accounts.emails.send_mail', side_effect=OSError('smtp down')):
            with self.assertLogs('accounts.emails', level='ERROR'):
                response = self.signup()
        self.assertRedirects(response, reverse('verify_email'))
        self.assertEqual(len(mail.outbox), 0)
        self.age_code(EmailVerification.RESEND_COOLDOWN)
        self.client.post(reverse('resend_code'))
        self.verify(self.last_code())
        self.assertTrue(User.objects.get(username='newbie').is_active)


class ResendTests(SignUpFlowTestCase):
    def test_resend_respects_cooldown(self):
        self.signup()
        self.client.post(reverse('resend_code'))
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_invalidates_previous_code(self):
        self.signup()
        old_code = self.last_code()
        self.age_code(EmailVerification.RESEND_COOLDOWN)
        with mock.patch('accounts.models.secrets.choice', return_value='7' if old_code[0] != '7' else '8'):
            self.client.post(reverse('resend_code'))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.verify(old_code).status_code, 200)
        self.assertFalse(User.objects.get(username='newbie').is_active)
        self.verify(self.last_code())
        self.assertTrue(User.objects.get(username='newbie').is_active)

    def test_resend_requires_post(self):
        self.assertEqual(self.client.get(reverse('resend_code')).status_code, 405)


class LoginTests(SignUpFlowTestCase):
    def login(self, username, password=PASSWORD):
        return self.client.post(reverse('login'), {'username': username, 'password': password})

    def test_unverified_user_is_sent_to_verification(self):
        self.signup()
        self.client.session.flush()  # другой браузер: сессии с регистрацией нет
        self.age_code(EmailVerification.RESEND_COOLDOWN)
        response = self.login('newbie')
        self.assertRedirects(response, reverse('verify_email'))
        self.assertFalse(self.is_logged_in())
        self.assertEqual(len(mail.outbox), 2)
        self.verify(self.last_code())
        self.assertTrue(self.is_logged_in())

    def test_unverified_user_with_wrong_password_gets_no_code(self):
        self.signup()
        self.client.session.flush()
        response = self.login('newbie', 'wrong-password')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('pending_user_id', self.client.session)

    def test_active_user_logs_in_normally(self):
        User.objects.create_user('regular', email='r@example.com', password=PASSWORD)
        self.assertRedirects(self.login('regular'), reverse('ads:list'))
        self.assertTrue(self.is_logged_in())

    def test_deactivated_user_without_verification_cannot_login(self):
        User.objects.create_user('banned', email='b@example.com', password=PASSWORD, is_active=False)
        self.assertEqual(self.login('banned').status_code, 200)
        self.assertFalse(self.is_logged_in())
        self.assertEqual(len(mail.outbox), 0)

    def test_pages_render(self):
        for name in ('login', 'signup'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
