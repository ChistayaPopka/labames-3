from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import EmailVerification

User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        label='Электронная почта',
        help_text='На этот адрес придёт код подтверждения.',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Пользователь с такой почтой уже зарегистрирован.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = False  # станет активным после подтверждения почты
        if commit:
            user.save()
        return user


class VerificationCodeForm(forms.Form):
    code = forms.CharField(
        label='Код из письма',
        min_length=EmailVerification.CODE_LENGTH,
        max_length=EmailVerification.CODE_LENGTH,
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'autofocus': True,
            'placeholder': '000000',
            'class': 'code-input',
        }),
    )

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not code.isdigit():
            raise forms.ValidationError('Код состоит только из цифр.')
        return code
