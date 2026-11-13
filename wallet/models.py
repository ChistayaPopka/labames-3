from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

MONEY = {'max_digits': 12, 'decimal_places': 2}


class Wallet(models.Model):
    """Тестовый кошелёк пользователя. Деньги ненастоящие.

    balance — свободные средства, held — замороженные под активные брони.
    Менять суммы можно только через wallet.services: там каждая операция
    пишется в журнал Transaction и выполняется атомарным условным UPDATE.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name='пользователь',
    )
    balance = models.DecimalField('доступно, ₽', default=Decimal('0'), **MONEY)
    held = models.DecimalField('заморожено, ₽', default=Decimal('0'), **MONEY)

    class Meta:
        verbose_name = 'кошелёк'
        verbose_name_plural = 'кошельки'
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name='wallet_balance_non_negative'),
            models.CheckConstraint(condition=Q(held__gte=0), name='wallet_held_non_negative'),
        ]

    def __str__(self):
        return f'Кошелёк {self.user}'


class Order(models.Model):
    """Бронь объявления: деньги покупателя заморожены до подтверждения или отмены."""

    class Status(models.TextChoices):
        RESERVED = 'reserved', 'Забронирован'
        COMPLETED = 'completed', 'Завершён'
        CANCELLED = 'cancelled', 'Отменён'
        EXPIRED = 'expired', 'Истёк срок'

    ad = models.ForeignKey(
        'ads.Ad',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='объявление',
    )
    # Снимок названия: заказ остаётся читаемым, даже если объявление удалят
    ad_title = models.CharField('объявление (название)', max_length=120)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='purchases',
        verbose_name='покупатель',
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='sales',
        verbose_name='продавец',
    )
    # Цена фиксируется в момент брони — продавец не сможет её поменять задним числом
    amount = models.DecimalField('сумма, ₽', **MONEY)
    status = models.CharField('статус', max_length=10, choices=Status.choices, default=Status.RESERVED)
    created_at = models.DateTimeField('создан', auto_now_add=True)
    expires_at = models.DateTimeField('бронь до')
    closed_at = models.DateTimeField('закрыт', null=True, blank=True)

    class Meta:
        verbose_name = 'заказ'
        verbose_name_plural = 'заказы'
        ordering = ['-created_at']
        constraints = [
            # Не больше одной активной брони на объявление — защита от гонки двух покупателей
            models.UniqueConstraint(
                fields=['ad'],
                condition=Q(status='reserved'),
                name='one_active_reservation_per_ad',
            ),
            models.CheckConstraint(condition=Q(amount__gte=0), name='order_amount_non_negative'),
        ]
        indexes = [models.Index(fields=['status', 'expires_at'])]

    def __str__(self):
        return f'Заказ №{self.pk}: {self.ad_title}'

    @property
    def is_active(self):
        return self.status == self.Status.RESERVED and self.expires_at > timezone.now()


class Transaction(models.Model):
    """Запись журнала операций. Записи только добавляются и никогда не меняются.

    amount всегда положительная; как операция влияет на доступные и замороженные
    средства, показывают balance_delta и held_delta. Сумма этих дельт по журналу
    совпадает с текущими balance и held кошелька.
    """

    class Kind(models.TextChoices):
        TOPUP = 'topup', 'Пополнение'
        HOLD = 'hold', 'Заморозка под бронь'
        RELEASE = 'release', 'Возврат брони'
        CHARGE = 'charge', 'Оплата заказа'
        PAYOUT = 'payout', 'Поступление от продажи'

    # (изменение доступных, изменение замороженных) на единицу суммы
    EFFECTS = {
        Kind.TOPUP: (1, 0),
        Kind.HOLD: (-1, 1),
        Kind.RELEASE: (1, -1),
        Kind.CHARGE: (0, -1),
        Kind.PAYOUT: (1, 0),
    }

    wallet = models.ForeignKey(
        Wallet, on_delete=models.CASCADE, related_name='transactions', verbose_name='кошелёк',
    )
    kind = models.CharField('тип', max_length=10, choices=Kind.choices)
    amount = models.DecimalField('сумма, ₽', **MONEY)
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        verbose_name='заказ',
    )
    comment = models.CharField('комментарий', max_length=200, blank=True)
    created_at = models.DateTimeField('дата', auto_now_add=True)

    class Meta:
        verbose_name = 'операция'
        verbose_name_plural = 'журнал операций'
        ordering = ['-created_at', '-pk']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name='transaction_amount_non_negative'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} {self.amount} ₽'

    @property
    def balance_delta(self):
        return self.amount * self.EFFECTS[self.kind][0]

    @property
    def held_delta(self):
        return self.amount * self.EFFECTS[self.kind][1]
