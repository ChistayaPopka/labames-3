from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class Category(models.Model):
    name = models.CharField('название', max_length=60, unique=True)
    slug = models.SlugField('слаг', max_length=60, unique=True)

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'категории'
        ordering = ['name']

    def __str__(self):
        return self.name


class Ad(models.Model):
    class Condition(models.TextChoices):
        NEW = 'new', 'Новое'
        USED = 'used', 'Б/у'

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ads',
        verbose_name='автор',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='ads',
        verbose_name='категория',
    )
    title = models.CharField('заголовок', max_length=120)
    description = models.TextField('описание')
    price = models.DecimalField(
        'цена, ₽',
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    condition = models.CharField(
        'состояние',
        max_length=4,
        choices=Condition.choices,
        default=Condition.USED,
    )
    city = models.CharField('город', max_length=80)
    phone = models.CharField('телефон', max_length=30, blank=True)
    image = models.ImageField('фото', upload_to='ads/%Y/%m/', blank=True)
    is_active = models.BooleanField('активно', default=True)
    views = models.PositiveIntegerField('просмотры', default=0, editable=False)
    favorited_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='favorite_ads',
        blank=True,
        verbose_name='в избранном у',
    )
    created_at = models.DateTimeField('создано', auto_now_add=True)
    updated_at = models.DateTimeField('обновлено', auto_now=True)

    class Meta:
        verbose_name = 'объявление'
        verbose_name_plural = 'объявления'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['is_active', '-created_at'])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('ads:detail', kwargs={'pk': self.pk})
