from django import forms

from .models import MESSAGE_MAX_LENGTH


class MessageForm(forms.Form):
    text = forms.CharField(
        label='Сообщение',
        max_length=MESSAGE_MAX_LENGTH,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Напишите сообщение…',
            'maxlength': MESSAGE_MAX_LENGTH,
        }),
        error_messages={'required': 'Сообщение пустое.'},
    )
