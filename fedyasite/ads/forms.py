from django import forms
from django.db.models import Q

from .models import Ad, Category


class AdForm(forms.ModelForm):
    class Meta:
        model = Ad
        fields = (
            'title', 'category', 'condition', 'price', 'city',
            'phone', 'description', 'image', 'is_active',
        )
        widgets = {
            'description': forms.Textarea(attrs={'rows': 6}),
        }


class AdFilterForm(forms.Form):
    SORT_CHOICES = [
        ('new', 'Сначала новые'),
        ('cheap', 'Сначала дешёвые'),
        ('expensive', 'Сначала дорогие'),
        ('popular', 'По популярности'),
    ]
    SORT_FIELDS = {
        'new': '-created_at',
        'cheap': 'price',
        'expensive': '-price',
        'popular': '-views',
    }

    q = forms.CharField(
        label='Поиск', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Что ищете?'}),
    )
    category = forms.ModelChoiceField(
        label='Категория', required=False,
        queryset=Category.objects.all(), to_field_name='slug',
        empty_label='Все категории',
    )
    city = forms.CharField(label='Город', required=False)
    price_min = forms.DecimalField(label='Цена от', required=False, min_value=0)
    price_max = forms.DecimalField(label='Цена до', required=False, min_value=0)
    condition = forms.ChoiceField(
        label='Состояние', required=False,
        choices=[('', 'Любое')] + Ad.Condition.choices,
    )
    sort = forms.ChoiceField(label='Сортировка', required=False, choices=SORT_CHOICES)

    def filter(self, queryset):
        """Применяет заполненные фильтры к queryset объявлений."""
        if not self.is_valid():
            return queryset
        data = self.cleaned_data
        if data['q']:
            # SQLite не умеет регистронезависимый LIKE для кириллицы,
            # поэтому сравниваем по нескольким вариантам регистра.
            q = data['q'].strip()
            variants = {q, q.lower(), q.capitalize(), q.upper()}
            condition = Q()
            for v in variants:
                condition |= Q(title__contains=v) | Q(description__contains=v)
            queryset = queryset.filter(condition)
        if data['category']:
            queryset = queryset.filter(category=data['category'])
        if data['city']:
            city = data['city'].strip()
            queryset = queryset.filter(
                city__in={city, city.lower(), city.capitalize(), city.title()}
            )
        if data['price_min'] is not None:
            queryset = queryset.filter(price__gte=data['price_min'])
        if data['price_max'] is not None:
            queryset = queryset.filter(price__lte=data['price_max'])
        if data['condition']:
            queryset = queryset.filter(condition=data['condition'])
        return queryset.order_by(self.SORT_FIELDS.get(data['sort'], '-created_at'))
