from django.urls import path

from . import views

app_name = 'chat'

urlpatterns = [
    path('messages/', views.InboxView.as_view(), name='inbox'),
    path('messages/<int:pk>/', views.ConversationView.as_view(), name='detail'),
    path('messages/<int:pk>/updates/', views.ConversationUpdatesView.as_view(), name='updates'),
    path('ads/<int:pk>/write/', views.ConversationStartView.as_view(), name='start'),
]
