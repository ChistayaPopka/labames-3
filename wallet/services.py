"""Все операции с тестовым балансом.

Правила, которые здесь соблюдаются:
- суммы меняются только условным UPDATE с F-выражениями
  (`filter(balance__gte=x).update(balance=F('balance') - x)`): проверка и списание
  выполняются одним SQL-запросом, поэтому два одновременных клика не уведут баланс
  в минус. Это работает и на SQLite, где select_for_update ничего не делает;
- смена статуса заказа тоже условная (`filter(status=RESERVED).update(...)`), так что
  заказ нельзя завершить или отменить дважды;
- каждая операция пишется в журнал Transaction в той же транзакции БД.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone

from ads.models import Ad

from .models import Order, Transaction, Wallet

RESERVATION_HOURS = getattr(settings, 'WALLET_RESERVATION_HOURS', 48)
TOPUP_MAX = Decimal(getattr(settings, 'WALLET_TOPUP_MAX', 100_000))
BALANCE_MAX = Decimal(getattr(settings, 'WALLET_BALANCE_MAX', 1_000_000))


class WalletError(Exception):
    """Операцию нельзя выполнить; текст ошибки можно показать пользователю."""


def get_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def _log(wallet_id, kind, amount, order=None, comment=''):
    Transaction.objects.create(
        wallet_id=wallet_id, kind=kind, amount=amount, order=order, comment=comment,
    )


def active_reservations():
    """Брони, которые сейчас держат объявление. Просроченные, но ещё не закрытые, не считаются."""
    return Order.objects.filter(status=Order.Status.RESERVED, expires_at__gt=timezone.now())


def ad_is_reserved():
    """Выражение для annotate/filter по Ad: есть ли у объявления активная бронь."""
    return Exists(active_reservations().filter(ad=OuterRef('pk')))


# --- Пополнение ---------------------------------------------------------------

@transaction.atomic
def top_up(user, amount, comment=''):
    amount = Decimal(amount)
    if amount <= 0:
        raise WalletError('Сумма пополнения должна быть больше нуля.')
    if amount > TOPUP_MAX:
        raise WalletError(f'За один раз можно пополнить не больше {TOPUP_MAX:,.0f} ₽.'.replace(',', ' '))
    wallet = get_wallet(user)
    updated = Wallet.objects.filter(
        pk=wallet.pk, balance__lte=BALANCE_MAX - amount,
    ).update(balance=F('balance') + amount)
    if not updated:
        raise WalletError(
            f'Баланс не может превышать {BALANCE_MAX:,.0f} ₽.'.replace(',', ' ')
        )
    _log(wallet.pk, Transaction.Kind.TOPUP, amount, comment=comment)
    return wallet


# --- Бронирование -------------------------------------------------------------

@transaction.atomic
def reserve(ad_id, buyer):
    """Бронирует объявление: цена переходит из доступных средств покупателя в замороженные."""
    expire_overdue(Order.objects.filter(ad_id=ad_id))

    ad = Ad.objects.filter(pk=ad_id).first()
    if ad is None or not ad.is_active:
        raise WalletError('Объявление недоступно для покупки.')
    if ad.author_id == buyer.pk:
        raise WalletError('Нельзя забронировать собственное объявление.')

    wallet = get_wallet(buyer)
    order = Order(
        ad=ad,
        ad_title=ad.title,
        buyer=buyer,
        seller_id=ad.author_id,
        amount=ad.price,
        expires_at=timezone.now() + timedelta(hours=RESERVATION_HOURS),
    )
    try:
        # Вложенный atomic — точка сохранения, чтобы IntegrityError не сломал внешнюю транзакцию
        with transaction.atomic():
            order.save()
    except IntegrityError:
        raise WalletError('Это объявление уже забронировал другой покупатель.') from None

    updated = Wallet.objects.filter(pk=wallet.pk, balance__gte=order.amount).update(
        balance=F('balance') - order.amount,
        held=F('held') + order.amount,
    )
    if not updated:
        # Исключение откатит и созданный заказ
        raise WalletError('Недостаточно средств на балансе.')
    _log(wallet.pk, Transaction.Kind.HOLD, order.amount, order=order)
    return order


def _release(order, status):
    """Возвращает замороженные деньги покупателю. Вызывать внутри transaction.atomic.

    Возвращает False, если заказ уже не активен (его закрыли параллельно).
    """
    updated = Order.objects.filter(pk=order.pk, status=Order.Status.RESERVED).update(
        status=status, closed_at=timezone.now(),
    )
    if not updated:
        return False
    wallet = get_wallet(order.buyer)
    moved = Wallet.objects.filter(pk=wallet.pk, held__gte=order.amount).update(
        held=F('held') - order.amount,
        balance=F('balance') + order.amount,
    )
    if not moved:
        raise RuntimeError(f'В кошельке {wallet.pk} не хватает замороженных средств для заказа {order.pk}')
    _log(wallet.pk, Transaction.Kind.RELEASE, order.amount, order=order)
    order.status = status
    return True


def expire_overdue(queryset=None):
    """Закрывает просроченные брони и возвращает деньги. Возвращает число закрытых заказов."""
    queryset = Order.objects.all() if queryset is None else queryset
    overdue = queryset.filter(status=Order.Status.RESERVED, expires_at__lte=timezone.now())
    count = 0
    for order in overdue.select_related('buyer'):
        with transaction.atomic():
            count += _release(order, Order.Status.EXPIRED)
    return count


def _get_order(order_id):
    # Сначала обрабатываем просрочку, чтобы истёкшую бронь нельзя было завершить.
    # Вызывать ВНЕ общей транзакции: иначе последующий WalletError откатит и возврат денег.
    expire_overdue(Order.objects.filter(pk=order_id))
    order = Order.objects.select_related('buyer', 'seller').filter(pk=order_id).first()
    if order is None:
        raise WalletError('Заказ не найден.')
    return order


def complete(order_id, user):
    """Покупатель подтвердил получение: замороженные деньги уходят продавцу."""
    order = _get_order(order_id)
    if order.buyer_id != user.pk:
        raise WalletError('Подтвердить получение может только покупатель.')
    with transaction.atomic():
        return _complete(order)


def _complete(order):
    updated =Order.objects.filter(pk=order.pk, status=Order.Status.RESERVED).update(
        status=Order.Status.COMPLETED, closed_at=timezone.now(),
    )
    if not updated:
        raise WalletError('Заказ уже закрыт.')

    buyer_wallet = get_wallet(order.buyer)
    seller_wallet = get_wallet(order.seller)
    charged = Wallet.objects.filter(pk=buyer_wallet.pk, held__gte=order.amount).update(
        held=F('held') - order.amount,
    )
    if not charged:
        raise RuntimeError(f'В кошельке {buyer_wallet.pk} не хватает замороженных средств для заказа {order.pk}')
    Wallet.objects.filter(pk=seller_wallet.pk).update(balance=F('balance') + order.amount)
    _log(buyer_wallet.pk, Transaction.Kind.CHARGE, order.amount, order=order)
    _log(seller_wallet.pk, Transaction.Kind.PAYOUT, order.amount, order=order)

    # Товар продан — снимаем объявление с публикации
    if order.ad_id:
        Ad.objects.filter(pk=order.ad_id).update(is_active=False)
    order.status = Order.Status.COMPLETED
    return order


def cancel(order_id, user):
    """Отмена брони покупателем или продавцом: деньги возвращаются покупателю."""
    order = _get_order(order_id)
    if user.pk not in (order.buyer_id, order.seller_id):
        raise WalletError('Отменить заказ может только покупатель или продавец.')
    with transaction.atomic():
        released = _release(order, Order.Status.CANCELLED)
    if not released:
        raise WalletError('Заказ уже закрыт.')
    return order
