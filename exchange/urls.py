# exchange/urls.py (¡Archivo nuevo!)

from django.urls import path
from .views import (
    exchange_volume_chart_data,
    DashboardView,
    ClientListView,
    ClientDetailView,
    ClientCreateView,
    ClientUpdateView,
    ClientDeleteView,
    TransactionCreateView,
    TransactionUpdateView,
    AdminPasswordVerifyView,
    # Aquí irán las otras vistas que creemos, como ClientListView, etc.
)
from . import views # Importamos las vistas
from .views import TransactionDeleteView
from exchange.views import custom_permission_denied_view
from .views import DailySessionView, open_session, close_session

urlpatterns = [
    # URL para la API de datos del gráfico
    path('api/chart-data/', views.exchange_volume_chart_data, name='chart-data'),
    path('', DashboardView.as_view(), name='dashboard'),
    path('clients/', ClientListView.as_view(), name='client-list'),
    path('clients/new/', ClientCreateView.as_view(), name='client-create'),
    path('clients/<int:pk>/', ClientDetailView.as_view(), name='client-detail'),
    path('clients/<int:pk>/edit/', ClientUpdateView.as_view(), name='client-update'),
    path('clients/<int:pk>/delete/', ClientDeleteView.as_view(), name='client-delete'), 
    path('clients/<int:client_pk>/transaction/new/', TransactionCreateView.as_view(), name='transaction-create'),
    path('transactions/<int:pk>/update/', TransactionUpdateView.as_view(), name='transaction-update'),
    path('verify-admin/', AdminPasswordVerifyView.as_view(), name='admin-verify'),
    path('transactions/<int:pk>/delete/', TransactionDeleteView.as_view(), name='transaction-delete'),
    path('session/', DailySessionView.as_view(), name='daily-session'),
    path('session/open/', open_session, name='open-session'),
    path('session/close/', close_session, name='close-session'),
    
    # Aquí puedes agregar las URLs de las otras páginas más adelante
    # path('clients/', views.ClientListView.as_view(), name='client-list'),
]

handler403 = custom_permission_denied_view