from .models import Wallet


def wallet(request):
    """Баланс для шапки сайта. Кошелёк здесь не создаётся — только читается."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    w = Wallet.objects.filter(user=user).only('balance', 'held').first()
    return {'header_wallet': w or Wallet(balance=0, held=0)}
