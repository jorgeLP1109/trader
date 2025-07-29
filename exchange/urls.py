# exchange/urls.py

from django.urls import path
from .views import (
    # Vistas principales
    DashboardView,
    
    # Vistas de Clientes
    ClientListView, ClientDetailView, ClientCreateView, ClientUpdateView, ClientDeleteView,
    
    # Vistas de Operaciones Avanzadas
    AdvancedTransactionCreateView, AdvancedTransactionUpdateView, AdvancedTransactionDeleteView,
    AdvancedTransactionCancelView, update_transaction_status_ajax,
    
    # Vistas de Hojas de Trabajo
    WorkSheetView, add_transaction_to_worksheet_ajax, close_worksheet, reopen_worksheet,

    # Vistas de Gestión de Caja
    VaultManagementView, open_vault_session, close_vault_session, reopen_vault_session, VaultAdjustmentView,
    
    # Vistas de Reportes
    DailySessionReportView, GeneralReportView, ClientReportView, PendingTransactionsReportView, ProfitReportView,
    
    # Vistas de Exportación
    export_general_report_csv,
    
    # Vistas de Administración y Seguridad
    AdminPasswordVerifyView,
    ResetDataView, # <--- ¡Asegurándose de que esté aquí!
    
    # Vistas de API para gráficos
    exchange_volume_chart_data,
    operation_composition_chart_data,
    monthly_flow_chart_data
)

urlpatterns = [
    # Dashboard
    path('', DashboardView.as_view(), name='dashboard'),

    # Clientes
    path('clients/', ClientListView.as_view(), name='client-list'),
    path('clients/new/', ClientCreateView.as_view(), name='client-create'),
    path('clients/<int:pk>/', ClientDetailView.as_view(), name='client-detail'),
    path('clients/<int:pk>/edit/', ClientUpdateView.as_view(), name='client-update'),
    path('clients/<int:pk>/delete/', ClientDeleteView.as_view(), name='client-delete'),

    # Hojas de Trabajo
    path('clients/<int:client_pk>/worksheet/', WorkSheetView.as_view(), name='client-worksheet'),
    path('worksheet/<int:worksheet_id>/add/', add_transaction_to_worksheet_ajax, name='add-transaction-to-worksheet-ajax'),
    path('worksheet/<int:worksheet_id>/close/', close_worksheet, name='close-worksheet'),
    path('worksheet/<int:worksheet_id>/reopen/', reopen_worksheet, name='reopen-worksheet'),
    
    # Operaciones
    path('clients/<int:client_pk>/new-operation/', AdvancedTransactionCreateView.as_view(), name='advanced-transaction-create'),
    path('operations/<int:pk>/update/', AdvancedTransactionUpdateView.as_view(), name='advanced-transaction-update'),
    path('operations/<int:pk>/delete/', AdvancedTransactionDeleteView.as_view(), name='advanced-transaction-delete'),
    path('operations/<int:pk>/cancel/', AdvancedTransactionCancelView.as_view(), name='advanced-transaction-cancel'),
    path('operations/<int:pk>/update-status/', update_transaction_status_ajax, name='update-transaction-status-ajax'),
    
    # Cajas/Bóvedas
    path('vaults/', VaultManagementView.as_view(), name='vault-management'),
    path('vaults/<int:vault_id>/open/', open_vault_session, name='open-vault-session'),
    path('vaults/<int:vault_id>/close/', close_vault_session, name='close-vault-session'),
    path('vaults/<int:vault_id>/adjust/', VaultAdjustmentView.as_view(), name='vault-adjustment'),
    path('vaults/session/<int:session_id>/reopen/', reopen_vault_session, name='reopen-vault-session'),
    
    # Reportes
    path('reports/daily-sessions/', DailySessionReportView.as_view(), name='report-daily-sessions'),
    path('reports/general/', GeneralReportView.as_view(), name='report-general'),
    path('reports/by-client/', ClientReportView.as_view(), name='report-by-client'),
    path('reports/pending/', PendingTransactionsReportView.as_view(), name='report-pending-transactions'),
    path('reports/profit/', ProfitReportView.as_view(), name='report-profit'),
    
    # Exportación
    path('export/general-report/', export_general_report_csv, name='export-general-report'),

    # Herramientas de Administración y Seguridad
    path('verify-admin/', AdminPasswordVerifyView.as_view(), name='admin-verify'),
    path('tools/reset-data/', ResetDataView.as_view(), name='reset-data'),
    
    # API de Gráficos
    path('api/chart-data/volume/', exchange_volume_chart_data, name='chart-volume-data'),
    path('api/chart-data/composition/', operation_composition_chart_data, name='chart-composition-data'),
    path('api/chart-data/flow/', monthly_flow_chart_data, name='chart-flow-data'),
]