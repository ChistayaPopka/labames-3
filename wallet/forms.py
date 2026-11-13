from django import forms

from .services import TOPUP_MAX


class TopUpForm(forms.Form):
    amount = forms.DecimalField(
        label='Сумма, ₽',
        min_value=1,
        max_value=TOPUP_MAX,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '1', 'placeholder': '10000'}),
    )
