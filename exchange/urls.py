# exchange/urls.py

from django.urls import path
from .views import (
    # Vistas principales
    DashboardView,
    
    # Vistas de Clientes (CRUD)
    ClientListView,
    ClientDetailView,
    ClientCreateView,
    ClientUpdateView,
    ClientDeleteView,
    
    # Vistas de Operaciones Avanzadas (NUEVOS NOMBRES)
    AdvancedTransactionCreateView,
    # AdvancedTransactionUpdateView, # Aún no la hemos creado/adaptado del todo
    # AdvancedTransactionDeleteView, # Aún no la hemos creado/adaptado del todo
    
    # Vistas de Gestión de Caja
    VaultManagementView,
    open_vault_session,
    close_vault_session,
    
    # Vistas de Reportes
    DailySessionReportView,
    GeneralReportView,
    ClientReportView,
    
    # Vistas de API para gráficos
    exchange_volume_chart_data,
    operation_composition_chart_data,
    monthly_flow_chart_data,
    
    # Vista de verificación de admin
    AdminPasswordVerifyView,
)
from .views import AdvancedTransactionUpdateView, AdvancedTransactionDeleteView
from .views import AdvancedTransactionCancelView
from .views import export_general_report_csv 

urlpatterns = [
    # Dashboard
    path('', DashboardView.as_view(), name='dashboard'),

    # Clientes
    path('clients/', ClientListView.as_view(), name='client-list'),
    path('clients/new/', ClientCreateView.as_view(), name='client-create'),
    path('clients/<int:pk>/', ClientDetailView.as_view(), name='client-detail'),
    path('clients/<int:pk>/edit/', ClientUpdateView.as_view(), name='client-update'),
    path('clients/<int:pk>/delete/', ClientDeleteView.as_view(), name='client-delete'),

    # Operaciones Avanzadas (URL ACTUALIZADA)
    path('clients/<int:client_pk>/new-operation/', AdvancedTransactionCreateView.as_view(), name='advanced-transaction-create'),
    path('clients/<int:client_pk>/new-operation/', AdvancedTransactionCreateView.as_view(), name='advanced-transaction-create'),
    path('operations/<int:pk>/update/', AdvancedTransactionUpdateView.as_view(), name='advanced-transaction-update'),
    path('operations/<int:pk>/delete/', AdvancedTransactionDeleteView.as_view(), name='advanced-transaction-delete'),
    path('operations/<int:pk>/cancel/', AdvancedTransactionCancelView.as_view(), name='advanced-transaction-cancel'),

    # Gestión de Caja/Bóvedas
    path('vaults/', VaultManagementView.as_view(), name='vault-management'),
    path('vaults/<int:vault_id>/open/', open_vault_session, name='open-vault-session'),
    path('vaults/<int:vault_id>/close/', close_vault_session, name='close-vault-session'),

    # Reportes
    path('reports/daily-sessions/', DailySessionReportView.as_view(), name='report-daily-sessions'),
    path('reports/general/', GeneralReportView.as_view(), name='report-general'),
    path('reports/by-client/', ClientReportView.as_view(), name='report-by-client'),

    # API de Gráficos
    path('api/chart-data/volume/', exchange_volume_chart_data, name='chart-volume-data'),
    path('api/chart-data/composition/', operation_composition_chart_data, name='chart-composition-data'),
    path('api/chart-data/flow/', monthly_flow_chart_data, name='chart-flow-data'),

    # Verificación de Admin
    path('verify-admin/', AdminPasswordVerifyView.as_view(), name='admin-verify'),

    # --- URL DE EXPORTACIÓN ---
    path('export/general-report/', export_general_report_csv, name='export-general-report'),
]