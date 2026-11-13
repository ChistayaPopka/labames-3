from django.urls import path

from . import views

app_name = 'wallet'

urlpatterns = [
    path('wallet/', views.WalletView.as_view(), name='wallet'),
    path('wallet/topup/', views.TopUpView.as_view(), name='topup'),
    path('orders/', views.OrderListView.as_view(), name='orders'),
    path('orders/<int:pk>/complete/', views.OrderCompleteView.as_view(), name='complete'),
    path('orders/<int:pk>/cancel/', views.OrderCancelView.as_view(), name='cancel'),
    path('ads/<int:pk>/reserve/', views.ReserveView.as_view(), name='reserve'),
]
