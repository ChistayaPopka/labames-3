from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

MESSAGE_MAX_LENGTH = 2000


class Conversation(models.Model):
    """Переписка покупателя с продавцом по конкретному объявлению.

    На одно объявление у покупателя ровно один диалог. Если объявление удалят,
    переписка сохранится — заголовок хранится копией в ad_title.
    """
    ad = models.ForeignKey(
        'ads.Ad',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='conversations',
        verbose_name='объявление',
    )
    ad_title = models.CharField('заголовок объявления', max_length=120)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='buyer_conversations',
        verbose_name='покупатель',
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='seller_conversations',
        verbose_name='продавец',
    )
    created_at = models.DateTimeField('создан', auto_now_add=True)
    # Время последнего сообщения — по нему сортируется список диалогов
    updated_at = models.DateTimeField('последнее сообщение', default=timezone.now, db_index=True)

    class Meta:
        verbose_name = 'диалог'
        verbose_name_plural = 'диалоги'
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['ad', 'buyer'], name='chat_one_conversation_per_ad_buyer'),
        ]

    def __str__(self):
        return f'{self.ad_title}: {self.buyer} → {self.seller}'

    def get_absolute_url(self):
        return reverse('chat:detail', kwargs={'pk': self.pk})

    def other_user(self, user):
        return self.seller if user.pk == self.buyer_id else self.buyer

    def has_member(self, user):
        return user.pk in (self.buyer_id, self.seller_id)

    @classmethod
    def for_user(cls, user):
        return cls.objects.filter(Q(buyer=user) | Q(seller=user))


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='диалог',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        verbose_name='отправитель',
    )
    text = models.TextField('текст', max_length=MESSAGE_MAX_LENGTH)
    is_read = models.BooleanField('прочитано', default=False)
    created_at = models.DateTimeField('отправлено', auto_now_add=True)

    class Meta:
        verbose_name = 'сообщение'
        verbose_name_plural = 'сообщения'
        ordering = ['created_at', 'pk']
        indexes = [models.Index(fields=['conversation', 'is_read'])]

    def __str__(self):
        return f'{self.sender}: {self.text[:40]}'
