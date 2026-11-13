from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts import views as accounts_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/signup/', accounts_views.SignUpView.as_view(), name='signup'),
    path('accounts/verify/', accounts_views.VerifyEmailView.as_view(), name='verify_email'),
    path('accounts/verify/resend/', accounts_views.ResendCodeView.as_view(), name='resend_code'),
    # Свой LoginView стоит раньше стандартного из django.contrib.auth.urls
    path('accounts/login/', accounts_views.LoginView.as_view(), name='login'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('wallet.urls')),
    path('', include('chat.urls')),
    path('', include('ads.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
