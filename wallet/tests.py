from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ads.models import Ad, Category

from . import services
from .models import Order, Transaction, Wallet

User = get_user_model()


class WalletTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user('seller', password='pass12345')
        cls.buyer = User.objects.create_user('buyer', password='pass12345')
        cls.other = User.objects.create_user('other', password='pass12345')
        cat = Category.objects.create(name='Хобби', slug='hobby')
        cls.ad = Ad.objects.create(
            author=cls.seller, category=cat, title='Гитара', description='x',
            price=Decimal('9000'), city='Казань',
        )
        cls.cheap = Ad.objects.create(
            author=cls.seller, category=cat, title='Чехол', description='x',
            price=Decimal('500'), city='Казань',
        )

    def wallet(self, user):
        return services.get_wallet(user)

    def assertLedgerConsistent(self, *users):
        """Баланс кошелька всегда равен сумме журнала."""
        for user in users:
            w = self.wallet(user)
            txs = list(w.transactions.all())
            self.assertEqual(w.balance, sum((t.balance_delta for t in txs), Decimal('0')), user)
            self.assertEqual(w.held, sum((t.held_delta for t in txs), Decimal('0')), user)


class TopUpTests(WalletTestCase):
    def test_top_up_via_view(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse('wallet:topup'), {'amount': '5000'})
        self.assertRedirects(response, reverse('wallet:wallet'))
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('5000'))
        self.assertLedgerConsistent(self.buyer)

    def test_custom_amount_with_kopecks(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse('wallet:topup'), {'amount': '1500.50'}, follow=True)
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('1500.50'))
        self.assertContains(response, 'Баланс пополнен на 1')
        self.assertContains(response, '500,50 ₽')
        # Больше двух знаков после запятой и мусор — отклоняются, баланс не меняется
        for bad in ('10.555', 'abc', '', '100001'):
            self.client.post(reverse('wallet:topup'), {'amount': bad})
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('1500.50'))
        self.assertLedgerConsistent(self.buyer)

    def test_wallet_page_has_input_and_prefill(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('wallet:wallet'), {'amount': '8500.5'})
        self.assertContains(response, 'name="amount"')
        self.assertContains(response, 'value="8500.5"')
        response = self.client.get(reverse('wallet:wallet'), {'amount': '<script>'})
        self.assertContains(response, 'value=""')

    def test_detail_links_missing_amount(self):
        services.top_up(self.buyer, 500)
        self.client.force_login(self.buyer)
        response = self.client.get(self.ad.get_absolute_url())
        self.assertContains(response, '?amount=8500.00#topup')

    def test_limits(self):
        with self.assertRaises(services.WalletError):
            services.top_up(self.buyer, 0)
        with self.assertRaises(services.WalletError):
            services.top_up(self.buyer, services.TOPUP_MAX + 1)
        self.client.force_login(self.buyer)
        self.client.post(reverse('wallet:topup'), {'amount': '-100'})
        self.assertEqual(self.wallet(self.buyer).balance, 0)

    def test_balance_cap(self):
        for _ in range(int(services.BALANCE_MAX / services.TOPUP_MAX)):
            services.top_up(self.buyer, services.TOPUP_MAX)
        with self.assertRaises(services.WalletError):
            services.top_up(self.buyer, 1)
        self.assertEqual(self.wallet(self.buyer).balance, services.BALANCE_MAX)

    def test_login_required_and_post_only(self):
        response = self.client.get(reverse('wallet:wallet'))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse('wallet:topup')).status_code, 405)
        self.assertEqual(self.client.get(reverse('wallet:wallet')).status_code, 200)


class ReserveTests(WalletTestCase):
    def test_reserve_holds_money_and_greys_out_ad(self):
        services.top_up(self.buyer, 10000)
        self.client.force_login(self.buyer)
        response = self.client.post(reverse('wallet:reserve', args=[self.ad.pk]))
        self.assertRedirects(response, reverse('wallet:orders'))

        w = self.wallet(self.buyer)
        self.assertEqual((w.balance, w.held), (Decimal('1000'), Decimal('9000')))
        order = Order.objects.get()
        self.assertEqual((order.amount, order.seller, order.status), (Decimal('9000'), self.seller, 'reserved'))

        # Объявление остаётся в ленте, но помечено как забронированное
        response = self.client.get(reverse('ads:list'))
        reserved = {ad.title: ad.is_reserved for ad in response.context['ads']}
        self.assertEqual(reserved, {'Гитара': True, 'Чехол': False})
        self.assertContains(response, 'card-reserved', count=1)
        self.assertContains(self.client.get(self.ad.get_absolute_url()), 'Вы забронировали')
        self.assertLedgerConsistent(self.buyer)

    def test_insufficient_funds_creates_nothing(self):
        services.top_up(self.buyer, 1000)
        with self.assertRaises(services.WalletError):
            services.reserve(self.ad.pk, self.buyer)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('1000'))

    def test_cannot_reserve_own_or_inactive_ad(self):
        services.top_up(self.seller, 10000)
        with self.assertRaises(services.WalletError):
            services.reserve(self.ad.pk, self.seller)
        Ad.objects.filter(pk=self.cheap.pk).update(is_active=False)
        services.top_up(self.buyer, 10000)
        with self.assertRaises(services.WalletError):
            services.reserve(self.cheap.pk, self.buyer)

    def test_second_buyer_rejected(self):
        services.top_up(self.buyer, 10000)
        services.top_up(self.other, 10000)
        services.reserve(self.ad.pk, self.buyer)
        with self.assertRaises(services.WalletError):
            services.reserve(self.ad.pk, self.other)
        self.assertEqual(self.wallet(self.other).balance, Decimal('10000'))
        self.assertEqual(Order.objects.count(), 1)

    def test_price_fixed_at_reservation(self):
        services.top_up(self.buyer, 10000)
        order = services.reserve(self.ad.pk, self.buyer)
        Ad.objects.filter(pk=self.ad.pk).update(price=1)
        services.complete(order.pk, self.buyer)
        self.assertEqual(self.wallet(self.seller).balance, Decimal('9000'))

    def test_seller_cannot_delete_reserved_ad(self):
        services.top_up(self.buyer, 10000)
        services.reserve(self.ad.pk, self.buyer)
        self.client.force_login(self.seller)
        self.client.post(reverse('ads:delete', args=[self.ad.pk]))
        self.assertTrue(Ad.objects.filter(pk=self.ad.pk).exists())


class OrderFlowTests(WalletTestCase):
    def setUp(self):
        services.top_up(self.buyer, 10000)
        self.order = services.reserve(self.ad.pk, self.buyer)

    def test_complete_pays_seller_and_closes_ad(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse('wallet:complete', args=[self.order.pk]))
        buyer_w, seller_w = self.wallet(self.buyer), self.wallet(self.seller)
        self.assertEqual((buyer_w.balance, buyer_w.held), (Decimal('1000'), 0))
        self.assertEqual(seller_w.balance, Decimal('9000'))
        self.order.refresh_from_db()
        self.ad.refresh_from_db()
        self.assertEqual(self.order.status, 'completed')
        self.assertFalse(self.ad.is_active)
        self.assertLedgerConsistent(self.buyer, self.seller)

    def test_only_buyer_can_complete(self):
        for user in (self.seller, self.other):
            with self.assertRaises(services.WalletError):
                services.complete(self.order.pk, user)
        self.assertEqual(self.wallet(self.seller).balance, 0)

    def test_cancel_by_seller_refunds(self):
        self.client.force_login(self.seller)
        self.client.post(reverse('wallet:cancel', args=[self.order.pk]))
        w = self.wallet(self.buyer)
        self.assertEqual((w.balance, w.held), (Decimal('10000'), 0))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        # Объявление снова обычное, без приглушения
        response = self.client.get(reverse('ads:list'))
        self.assertNotContains(response, 'card-reserved')
        self.assertLedgerConsistent(self.buyer, self.seller)

    def test_cancel_from_ad_page(self):
        url = self.ad.get_absolute_url()
        for user in (self.buyer, self.seller):
            self.client.force_login(user)
            self.assertContains(self.client.get(url), 'Снять бронь')
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(url), 'Снять бронь')

        self.client.force_login(self.buyer)
        response = self.client.post(reverse('wallet:cancel', args=[self.order.pk]), {'next': url})
        self.assertRedirects(response, url)
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('10000'))
        self.assertContains(self.client.get(url), 'Забронировать за')

    def test_cancel_next_rejects_external_url(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse('wallet:cancel', args=[self.order.pk]), {'next': 'https://evil.example/'},
        )
        self.assertRedirects(response, f"{reverse('wallet:orders')}?tab=purchases")

    def test_stranger_cannot_cancel(self):
        with self.assertRaises(services.WalletError):
            services.cancel(self.order.pk, self.other)
        self.assertEqual(self.wallet(self.buyer).held, Decimal('9000'))

    def test_no_double_close(self):
        services.complete(self.order.pk, self.buyer)
        with self.assertRaises(services.WalletError):
            services.complete(self.order.pk, self.buyer)
        with self.assertRaises(services.WalletError):
            services.cancel(self.order.pk, self.buyer)
        self.assertEqual(self.wallet(self.seller).balance, Decimal('9000'))
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('1000'))
        self.assertLedgerConsistent(self.buyer, self.seller)

    def test_expired_reservation_refunded_by_command(self):
        Order.objects.filter(pk=self.order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        call_command('expire_orders', stdout=StringIO())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'expired')
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('10000'))
        self.assertLedgerConsistent(self.buyer)

    def test_expired_reservation_cannot_be_completed(self):
        Order.objects.filter(pk=self.order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(services.WalletError):
            services.complete(self.order.pk, self.buyer)
        # Но деньги при этом вернулись (просрочка обработана до проверки)
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('10000'))
        self.assertEqual(self.wallet(self.seller).balance, 0)

    def test_expired_ad_can_be_reserved_again(self):
        Order.objects.filter(pk=self.order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        services.top_up(self.other, 10000)
        services.reserve(self.ad.pk, self.other)
        self.assertEqual(self.wallet(self.buyer).balance, Decimal('10000'))
        self.assertEqual(self.wallet(self.other).held, Decimal('9000'))

    def test_orders_page_tabs(self):
        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(reverse('wallet:orders')), 'Гитара')
        self.client.force_login(self.seller)
        response = self.client.get(reverse('wallet:orders'), {'tab': 'sales'})
        self.assertContains(response, 'buyer')
        my = self.client.get(reverse('ads:my'))
        self.assertContains(my, 'Забронировано')

    def test_wallet_page_shows_history(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('wallet:wallet'))
        self.assertContains(response, 'Заморозка под бронь')
        self.assertEqual(Transaction.objects.filter(wallet__user=self.buyer).count(), 2)
        self.assertEqual(Wallet.objects.count(), 1)  # кошелёк продавца ещё не нужен
