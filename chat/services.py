from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from .models import Conversation, Message


class ChatError(Exception):
    pass


def unread_messages(user):
    """Входящие непрочитанные сообщения пользователя во всех диалогах."""
    return Message.objects.filter(
        Q(conversation__buyer=user) | Q(conversation__seller=user),
        is_read=False,
    ).exclude(sender=user)


def send_message(conversation, sender, text):
    if not conversation.has_member(sender):
        raise ChatError('Вы не участвуете в этом диалоге.')
    text = text.strip()
    if not text:
        raise ChatError('Сообщение пустое.')
    with transaction.atomic():
        message = Message.objects.create(conversation=conversation, sender=sender, text=text)
        Conversation.objects.filter(pk=conversation.pk).update(updated_at=message.created_at)
        conversation.updated_at = message.created_at
    return message


def start_conversation(ad, buyer, text):
    """Первое сообщение продавцу. Если диалог уже есть — пишет в него."""
    if ad.author_id == buyer.pk:
        raise ChatError('Нельзя написать самому себе.')
    if not ad.is_active:
        raise ChatError('Объявление снято с публикации.')
    try:
        with transaction.atomic():
            conversation, _ = Conversation.objects.get_or_create(
                ad=ad, buyer=buyer,
                defaults={'seller': ad.author, 'ad_title': ad.title, 'updated_at': timezone.now()},
            )
    except IntegrityError:
        # Параллельный запрос успел создать диалог первым
        conversation = Conversation.objects.get(ad=ad, buyer=buyer)
    send_message(conversation, buyer, text)
    return conversation


def mark_read(conversation, user, up_to_id=None):
    """Отмечает прочитанными входящие сообщения пользователя в диалоге."""
    qs = conversation.messages.filter(is_read=False).exclude(sender=user)
    if up_to_id is not None:
        qs = qs.filter(pk__lte=up_to_id)
    return qs.update(is_read=True)


def last_read_own_id(conversation, user):
    """id последнего своего сообщения, которое собеседник прочитал (для галочек)."""
    return (
        conversation.messages.filter(sender=user, is_read=True)
        .aggregate(m=Max('pk'))['m'] or 0
    )
