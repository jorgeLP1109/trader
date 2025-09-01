# exchange/views.py

from django import forms
from django.db.models import Sum, Count, Avg
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
)
from django.views import View
from .models import Client, Transaction, User, CashOnHand, DailySession, CashVault, VaultSession, AdvancedTransaction, ClientWorkSheet, VaultAdjustment
from .forms import AdvancedTransactionForm
from django.contrib.auth import authenticate
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from .decorators import admin_required
from decimal import Decimal 
from django.core.paginator import Paginator
import csv
from django.http import HttpResponse
from django.template.loader import render_to_string # Importante para AJAX
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from .forms import VaultAdjustmentForm
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth import logout
from django.utils import timezone
from datetime import date
from datetime import datetime, timedelta
from django.db import models 
from django.db.models import Q 
from django.db import transaction
from .forms import ResetDataForm





# ==============================================================================
# MIXINS DE SEGURIDAD (VERSIÓN FINAL)
# ==============================================================================

class AdminRequiredMixin(UserPassesTestMixin):
    """
    Mixin para restringir el acceso solo a usuarios con el rol 'admin'.
    Si el usuario no tiene permiso, cierra su sesión y lo redirige al login.
    """
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == 'admin'

    def handle_no_permission(self):
        messages.warning(self.request, "No tienes permisos de administrador. Por favor, inicia sesión con una cuenta autorizada.")
        logout(self.request)
        return redirect('login')


class AdminVerifiedMixin:
    """
    Mixin que verifica si el admin ha sido verificado recientemente.
    Si no, lo redirige a la página de verificación.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.session.get('admin_verified', False):
            verify_url = reverse_lazy('admin-verify') + f'?next={request.path_info}'
            return redirect(verify_url)
        return super().dispatch(request, *args, **kwargs)
    



class AdminPasswordVerifyView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = 'exchange/admin_password_verify.html'
    
    def test_func(self):
        # Asegura que solo los administradores puedan acceder a esta página
        return self.request.user.is_authenticated and self.request.user.role == 'admin'

    def get(self, request, *args, **kwargs):
        next_url = request.GET.get('next', '/')
        return render(request, self.template_name, {'next_url': next_url})

    def post(self, request, *args, **kwargs):
        password = request.POST.get('password')
        next_url = request.POST.get('next_url', '/')
        
        user = authenticate(username=request.user.username, password=password)
        
        if user is not None:
            # La contraseña es correcta, guardamos la bandera en la sesión.
            request.session['admin_verified'] = True
            
            # NO establecemos una expiración específica, por lo que durará
            # lo mismo que la sesión de login del navegador.
            
            messages.success(request, 'Verificación exitosa. Ahora puedes realizar la acción.')
            return redirect(next_url)
        else:
            messages.error(request, 'Contraseña incorrecta. Por favor, inténtalo de nuevo.')
            return redirect(request.path_info + f'?next={next_url}')
        
        

# ==============================================================================
# VISTAS PRINCIPALES (DASHBOARD)
# ==============================================================================

class DashboardView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = 'exchange/dashboard_enhanced.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Dashboard Principal - Ganancias y Flujo de Caja'

        # --- SALDOS DE CAJA ---
        vault_totals = CashVault.objects.aggregate(
            total_usd=Sum('balance_usd'),
            total_bs=Sum('balance_bs'),
            total_usdt=Sum('balance_usdt'),
            total_zelle=Sum('balance_zelle')
        )
        context['cash_on_hand_usd'] = vault_totals.get('total_usd') or 0
        context['cash_on_hand_bs'] = vault_totals.get('total_bs') or 0
        context['cash_on_hand_usdt'] = vault_totals.get('total_usdt') or 0
        context['cash_on_hand_zelle'] = vault_totals.get('total_zelle') or 0

        # --- MÉTRICAS DE RENDIMIENTO (ÚLTIMOS 30 DÍAS) ---
        from datetime import timedelta
        end_date = timezone.localdate()
        start_date = end_date - timedelta(days=30)
        
        recent_transactions = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )
        
        # Ganancias del mes usando campos mejorados
        profit_by_commission_usd = recent_transactions.filter(
            operation_type__in=['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
        ).aggregate(total=Sum('profit_usd_equivalent'))['total'] or Decimal('0.00')
        
        profit_by_spread_bs = recent_transactions.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(total=Sum('profit_bs_equivalent'))['total'] or Decimal('0.00')
        
        # Volumen operado (usando amount_primary para obtener el monto real de la operación)
        total_volume_usd = recent_transactions.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
        ).aggregate(total=Sum('amount_primary'))['total'] or Decimal('0.00')
        
        total_volume_usdt = recent_transactions.filter(
            operation_type__in=['USDT_FOR_CASH', 'USDT_FOR_BS']
        ).aggregate(total=Sum('amount_primary'))['total'] or Decimal('0.00')
        
        # --- MÉTRICAS DE RENDIMIENTO ---
        context['performance_metrics'] = {
            'total_profit_usd_last_30d': profit_by_commission_usd,
            'total_profit_bs_last_30d': profit_by_spread_bs,
            'total_transactions_last_30d': recent_transactions.count(),
            'total_volume_usd_last_30d': total_volume_usd,
            'total_volume_usdt_last_30d': total_volume_usdt,
            'avg_daily_transactions': recent_transactions.count() / 30,
            'avg_profit_per_transaction': (
                (profit_by_commission_usd + profit_by_spread_bs) / max(recent_transactions.count(), 1)
            ),
        }
        
        # --- TOP CLIENTES POR RENTABILIDAD (ÚLTIMOS 30 DÍAS) ---
        # Usar campos de equivalencia mejorados para mayor precisión
        context['top_profitable_clients'] = recent_transactions.values(
            'client__name', 'client__id'
        ).annotate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            total_transactions=Count('id')
        ).order_by('-total_profit_bs')[:5]  # Ordenar por ganancia en BS que es la principal
        
        # --- ACTIVIDAD RECIENTE (ÚLTIMAS 5 TRANSACCIONES) ---
        context['recent_activity'] = AdvancedTransaction.objects.filter(
            status='completed'
        ).select_related('client', 'operator').order_by('-created_at')[:5]
        
        # --- ESTADÍSTICAS POR TIPO DE OPERACIÓN ---
        operation_stats = []
        for op_code, op_name in AdvancedTransaction.OPERATION_CHOICES:
            op_count = recent_transactions.filter(operation_type=op_code).count()
            op_profit = recent_transactions.filter(operation_type=op_code).aggregate(
                total=Sum('profit')
            )['total'] or Decimal('0.00')
            
            if op_count > 0:
                operation_stats.append({
                    'name': op_name,
                    'code': op_code,
                    'count': op_count,
                    'profit': op_profit
                })
        
        context['operation_stats'] = sorted(operation_stats, key=lambda x: x['profit'], reverse=True)

        return context


# ==============================================================================
# VISTAS PARA CLIENTES (CRUD)
# ==============================================================================

class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = 'exchange/client_list.html'
    context_object_name = 'clients'
    paginate_by = 10

    def get_queryset(self):
        """
        Sobrescribimos este método para filtrar la lista de clientes.
        """
        queryset = super().get_queryset().order_by('name')
        
        # Obtenemos el término de búsqueda desde la URL (?q=...)
        search_query = self.request.GET.get('q', '')
        
        if search_query:
            # Filtramos por nombre O por identificador que contenga la búsqueda
            queryset = queryset.filter(
                Q(name__istartswith=search_query) | 
                Q(identifier__istartswith=search_query)
            )
            
        return queryset

    def get_context_data(self, **kwargs):
        """
        Añadimos el término de búsqueda al contexto para poder mostrarlo
        en el campo de búsqueda.
        """
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        return context

class ClientDetailView(LoginRequiredMixin, DetailView):
    model = Client
    template_name = 'exchange/client_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = self.get_object()
        # Apuntamos a la relación correcta 'adv_transactions'
        context['transactions'] = client.adv_transactions.order_by('-created_at')
        # Llamamos al nuevo método get_balance()
        context['balance'] = client.get_balance()
        return context

class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    fields = ['name', 'identifier', 'phone', 'email']
    template_name = 'exchange/client_form.html'
    success_url = reverse_lazy('client-list')
    
    def form_valid(self, form):
        messages.success(self.request, f"Cliente '{form.instance.name}' creado exitosamente.")
        return super().form_valid(form)

class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model = Client
    fields = ['name', 'identifier', 'phone', 'email']
    template_name = 'exchange/client_form.html'
    success_url = reverse_lazy('client-list')
    
    def form_valid(self, form):
        messages.success(self.request, f"Cliente '{form.instance.name}' actualizado exitosamente.")
        return super().form_valid(form)

class ClientDeleteView(LoginRequiredMixin, DeleteView):
    model = Client
    template_name = 'exchange/client_confirm_delete.html'
    success_url = reverse_lazy('client-list')
    
    def form_valid(self, form):
        client_name = self.object.name
        messages.success(self.request, f"Cliente '{client_name}' eliminado exitosamente.")
        return super().form_valid(form)


# ==============================================================================
# VISTAS PARA TRANSACCIONES (CRUD)
# ==============================================================================

class AdvancedTransactionCreateView(LoginRequiredMixin, CreateView):
    model = AdvancedTransaction
    form_class = AdvancedTransactionForm
    template_name = 'exchange/advanced_transaction_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        context['page_title'] = f"Nueva Operación para {client.name}"
        context['cancel_url'] = reverse_lazy('client-detail', kwargs={'pk': client.pk})
        return context

    def form_valid(self, form):
        # Asignamos el cliente y el operador antes de guardar
        form.instance.client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        form.instance.operator = self.request.user
        
        # La lógica de cálculo ya está en el método save() del modelo
        return super().form_valid(form)

    def get_success_url(self):
        # Volvemos al detalle del cliente después de crear la transacción
        messages.success(self.request, "Operación registrada exitosamente.")
        return reverse_lazy('client-detail', kwargs={'pk': self.kwargs['client_pk']})
    

class TransactionUpdateView(LoginRequiredMixin, AdminVerifiedMixin, UpdateView):
    # El resto de la clase se queda exactamente igual...
    model = Transaction
    template_name = 'exchange/transaction_form.html'
    fields = ['operation_type', 'amount_usd', 'exchange_rate', 'status', 'notes']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Actualizar Transacción #{self.object.id}'
        context['cancel_url'] = reverse_lazy('client-detail', kwargs={'pk': self.object.client.pk})
        return context

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['amount_usd'].widget.attrs.update({'id': 'id_amount_usd', 'onkeyup': 'calculateTotal()', 'autocomplete': 'off'})
        form.fields['exchange_rate'].widget.attrs.update({'id': 'id_exchange_rate', 'onkeyup': 'calculateTotal()', 'autocomplete': 'off'})
        form.fields['notes'].widget = forms.Textarea(attrs={'rows': 3})
        return form

    def get_success_url(self):
        return reverse_lazy('client-detail', kwargs={'pk': self.object.client.pk})
    
class TransactionDeleteView(LoginRequiredMixin, AdminVerifiedMixin, DeleteView):
    model = Transaction
    template_name = 'exchange/transaction_confirm_delete.html'
    context_object_name = 'transaction'

    def get_success_url(self):
        # Después de eliminar, volvemos al detalle del cliente
        messages.success(self.request, f"Transacción #{self.object.id} eliminada exitosamente.")
        return reverse_lazy('client-detail', kwargs={'pk': self.object.client.pk})    


# ==============================================================================
# VISTAS DE API PARA GRÁFICOS (VERSIÓN ACTUALIZADA)
# ==============================================================================

# exchange/views.py

# ... (mantén todos tus otros imports al principio del archivo) ...
# Asegúrate de que estos imports específicos estén presentes:
from django.http import JsonResponse
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncMonth
from django.contrib.auth.decorators import login_required
from .models import AdvancedTransaction

# ... (mantén todas tus otras vistas: DashboardView, ClientListView, etc.) ...


# ==============================================================================
# VISTAS DE API PARA GRÁFICOS (VERSIÓN FINAL Y COMPLETA)
# ==============================================================================

@login_required
def exchange_volume_chart_data(request):
    """
    API que devuelve el número de transacciones completadas por mes.
    """
    # Filtramos por status completado para obtener métricas reales
    data = AdvancedTransaction.objects.filter(status='completed') \
        .annotate(month=TruncMonth('created_at')) \
        .values('month') \
        .annotate(count=Count('id')) \
        .order_by('month')
    
    # Formateamos los datos para que Chart.js los entienda
    labels = [d['month'].strftime('%B %Y') for d in data]
    values = [d['count'] for d in data]
    
    return JsonResponse({'labels': labels, 'data': values})


@login_required
def operation_composition_chart_data(request):
    """
    API que devuelve la composición de tipos de operación completadas.
    """
    data = AdvancedTransaction.objects.filter(status='completed') \
        .values('operation_type') \
        .annotate(count=Count('id')) \
        .order_by('operation_type')

    # Mapeamos los nombres técnicos a nombres legibles para el gráfico
    operation_names = dict(AdvancedTransaction.OPERATION_CHOICES)
    labels = [operation_names.get(d['operation_type'], d['operation_type']) for d in data]
    values = [d['count'] for d in data]

    return JsonResponse({'labels': labels, 'data': values})


@login_required
def monthly_flow_chart_data(request):
    """
    API que devuelve el flujo total de USD (efectivo) y USDT movidos por mes.
    """
    data = AdvancedTransaction.objects.filter(status='completed') \
        .annotate(month=TruncMonth('created_at')) \
        .values('month') \
        .annotate(
            # Suma de USD en operaciones que involucran efectivo o Zelle como entrada
            total_usd_cash=Sum('amount_in', filter=Q(operation_type__in=['BUY_USD_FOR_BS', 'SELL_USD_FOR_BS', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH'])),
            # Suma de USDT en operaciones que lo involucran como entrada
            total_usdt=Sum('amount_in', filter=Q(operation_type__in=['USDT_FOR_CASH', 'USDT_FOR_BS']))
        ).order_by('month')

    labels = [d['month'].strftime('%B %Y') for d in data]
    usd_values = [d['total_usd_cash'] or 0 for d in data]
    usdt_values = [d['total_usdt'] or 0 for d in data]

    return JsonResponse({
        'labels': labels, 
        'usd_data': usd_values,
        'usdt_data': usdt_values
    })

# ==============================================================================
# VISTAS DE MANEJO DE ERRORES
# ==============================================================================

def custom_permission_denied_view(request, exception=None):
    """
    Vista personalizada para mostrar cuando ocurre un error 403 (Permission Denied).
    """
    return render(request, '403.html', status=403)


# ==============================================================================
# VISTAS PARA GESTIÓN DE CAJA DIARIA
# ==============================================================================

class DailySessionView(LoginRequiredMixin, View):
    template_name = 'exchange/daily_session.html'

    def get(self, request, *args, **kwargs):
        # Intentamos obtener la sesión activa
        active_session = DailySession.objects.filter(status='open').first()
        cash = CashOnHand.objects.first()
        
        # Verificamos si ya existe una sesión para hoy
        session_today_exists = DailySession.objects.filter(date=date.today()).exists()

        context = {
            'active_session': active_session,
            'cash_on_hand': cash,
            'session_today_exists': session_today_exists,
        }
        return render(request, self.template_name, context)

def open_session(request):
    if request.method == 'POST':
        # Validar que no haya otra sesión abierta
        if DailySession.objects.filter(status='open').exists():
            messages.error(request, 'Ya hay una sesión de caja abierta. Debe cerrarla primero.')
            return redirect('daily-session')

        # Validar que no se haya abierto ya una caja hoy
        if DailySession.objects.filter(date=date.today()).exists():
            messages.error(request, 'Ya se ha operado con la caja en la fecha de hoy.')
            return redirect('daily-session')

        usd_str = request.POST.get('opening_balance_usd')
        bs_str = request.POST.get('opening_balance_bs')

        try:
            opening_usd = float(usd_str)
            opening_bs = float(bs_str)
        except (ValueError, TypeError):
            messages.error(request, 'Por favor, ingrese montos válidos.')
            return redirect('daily-session')

        # Creamos la nueva sesión
        DailySession.objects.create(
            date=date.today(),
            status='open',
            opening_balance_usd=opening_usd,
            opening_balance_bs=opening_bs,
            opened_by=request.user,
            opened_at=timezone.now()
        )
        
        # Actualizamos la caja principal con estos saldos iniciales
        cash, _ = CashOnHand.objects.get_or_create(pk=1)
        cash.total_usd = opening_usd
        cash.total_bs = opening_bs
        cash.save()
        
        messages.success(request, f"Caja abierta exitosamente con ${opening_usd} y {opening_bs} Bs.")
    return redirect('daily-session')


def close_session(request):
    if request.method == 'POST':
        active_session = DailySession.objects.filter(status='open').first()
        if not active_session:
            messages.error(request, 'No hay ninguna sesión de caja abierta para cerrar.')
            return redirect('daily-session')

        cash = CashOnHand.objects.first()
        
        # Guardamos los saldos de cierre
        active_session.closing_balance_usd = cash.total_usd
        active_session.closing_balance_bs = cash.total_bs
        active_session.status = 'closed'
        active_session.closed_by = request.user
        active_session.closed_at = timezone.now()
        active_session.save()
        
        messages.success(request, f"Caja cerrada exitosamente. El saldo final fue ${cash.total_usd} y {cash.total_bs} Bs.")
    return redirect('daily-session')


class DailySessionReportView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = VaultSession
    template_name = 'exchange/daily_session_report.html'
    context_object_name = 'sessions'
    # La paginación necesita un ordenamiento definido para ser consistente
    queryset = VaultSession.objects.filter(status='closed').order_by('-date') 
    paginate_by = 15 # Puedes ajustar este número




class GeneralReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/reports/profit_loss_report.html'
    
    def get(self, request, *args, **kwargs):
        # --- 1. FILTROS ---
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        operation_filter = request.GET.get('operation_type', '')
        client_filter = request.GET.get('client_id', '')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # --- 2. QUERYSET BASE (Solo transacciones completadas) ---
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('client', 'operator').order_by('-created_at')
        
        # Aplicar filtros adicionales
        if operation_filter:
            transactions_qs = transactions_qs.filter(operation_type=operation_filter)
        if client_filter and client_filter.isdigit():
            transactions_qs = transactions_qs.filter(client_id=client_filter)
        
        # --- 3. CÁLCULOS DE RESUMEN ---
        # Ganancias por tipo usando los nuevos campos mejorados
        profit_by_commission = transactions_qs.filter(
            operation_type__in=['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
        ).aggregate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            count=Count('id'),
            avg_profit_usd=Avg('profit_usd_equivalent')
        )
        
        profit_by_spread = transactions_qs.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            count=Count('id'),
            avg_profit_usd=Avg('profit_usd_equivalent')
        )
        
        # Volúmenes de operación (usando amount_primary para obtener el monto real operado)
        volumes = {
            'total_usd_moved': transactions_qs.filter(
                operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
            ).aggregate(total=Sum('amount_primary'))['total'] or Decimal('0.00'),
            
            'total_usdt_moved': transactions_qs.filter(
                operation_type__in=['USDT_FOR_CASH', 'USDT_FOR_BS']
            ).aggregate(total=Sum('amount_primary'))['total'] or Decimal('0.00'),
            
            'total_bs_moved': transactions_qs.filter(
                operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']
            ).aggregate(total=Sum('amount_in'))['total'] or Decimal('0.00'),  # Para BS sí usamos amount_in (lo que recibimos)
        }
        
        # Métricas de rentabilidad usando campos mejorados
        total_profit_usd = (
            (profit_by_commission['total_profit_usd'] or Decimal('0.00')) +
            (profit_by_spread['total_profit_usd'] or Decimal('0.00'))
        )
        
        total_profit_bs = (
            (profit_by_commission['total_profit_bs'] or Decimal('0.00')) +
            (profit_by_spread['total_profit_bs'] or Decimal('0.00'))
        )
        
        # Totales ya calculados con equivalencias
        total_profit_bs_equivalent = total_profit_bs
        
        # --- 4. ANÁLISIS POR PERÍODO ---
        # Ganancias por día de la semana
        daily_profits = []
        current_date = start_date
        while current_date <= end_date:
            day_transactions = transactions_qs.filter(created_at__date=current_date)
            day_profit_usd = day_transactions.aggregate(total=Sum('profit_usd_equivalent'))['total'] or Decimal('0.00')
            day_profit_bs = day_transactions.aggregate(total=Sum('profit_bs_equivalent'))['total'] or Decimal('0.00')
            daily_profits.append({
                'date': current_date,
                'profit_usd': day_profit_usd,
                'profit_bs': day_profit_bs,
                'transactions_count': day_transactions.count()
            })
            current_date += timedelta(days=1)
        
        # --- 5. TOP CLIENTES POR RENTABILIDAD ---
        top_clients = transactions_qs.values(
            'client__name', 'client__id'
        ).annotate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            total_transactions=Count('id'),
            total_volume=Sum('amount_in')
        ).order_by('-total_profit_usd')[:10]
        
        # --- 6. PAGINACIÓN ---
        paginator = Paginator(transactions_qs, 25)
        page_obj = paginator.get_page(request.GET.get('page'))
        
        context = {
            'page_title': 'Reporte de Ganancias y Pérdidas',
            'start_date': start_date,
            'end_date': end_date,
            'transactions': page_obj,
            'is_paginated': True,
            'page_obj': page_obj,
            
            # Resumen financiero
            'financial_summary': {
                'total_profit_usd': total_profit_usd,
                'total_profit_bs': total_profit_bs,
                'total_profit_bs_equivalent': total_profit_bs_equivalent,
                'total_transactions': transactions_qs.count(),
                'avg_profit_per_transaction': total_profit_bs_equivalent / max(transactions_qs.count(), 1),
            },
            
            # Análisis por tipo de operación
            'operation_analysis': {
                'commission_operations': {
                    'count': profit_by_commission['count'] or 0,
                    'total_profit_usd': profit_by_commission['total_profit_usd'] or Decimal('0.00'),
                    'total_profit_bs': profit_by_commission['total_profit_bs'] or Decimal('0.00'),
                    'avg_profit_usd': profit_by_commission['avg_profit_usd'] or Decimal('0.00'),
                },
                'spread_operations': {
                    'count': profit_by_spread['count'] or 0,
                    'total_profit_usd': profit_by_spread['total_profit_usd'] or Decimal('0.00'),
                    'total_profit_bs': profit_by_spread['total_profit_bs'] or Decimal('0.00'),
                    'avg_profit_usd': profit_by_spread['avg_profit_usd'] or Decimal('0.00'),
                }
            },
            
            'volumes': volumes,
            'daily_profits': daily_profits,
            'top_clients': top_clients,
            
            # Filtros para el template
            'operation_choices': AdvancedTransaction.OPERATION_CHOICES,
            'selected_operation': operation_filter,
            'clients': Client.objects.all().order_by('name'),
            'selected_client': int(client_filter) if client_filter.isdigit() else None,
        }
        
        return render(request, self.template_name, context)



class ClientReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/client_report.html'
    
    def get(self, request, *args, **kwargs):
        # --- 1. DATOS Y FILTROS ---
        all_clients = Client.objects.all().order_by('name')
        selected_client_id = request.GET.get('client', '')
        
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # --- 2. QUERYSET BASE Y FILTROS ---
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('client')

        if selected_client_id and selected_client_id.isdigit():
            transactions_qs = transactions_qs.filter(client_id=selected_client_id)
        
        # --- 3. CÁLCULOS DE VOLUMEN CORREGIDOS ---
        # Para el volumen total, usamos amount_primary que es el monto principal operado
        raw_volume = transactions_qs.aggregate(
            # USD que entra al inventario
            usd_in_buy=Sum('amount_primary', filter=Q(operation_type='BUY_USD_FOR_BS')),  # Cliente vende USD, nosotros compramos
            usd_in_commission=Sum('amount_out', filter=Q(operation_type__in=['USDT_FOR_CASH', 'ZELLE_FOR_CASH'])),  # Recibimos USD por servicios
            
            # USD que sale del inventario
            usd_out_sell=Sum('amount_primary', filter=Q(operation_type='SELL_USD_FOR_BS')),  # Vendemos USD al cliente
            usd_out_commission=Sum('amount_primary', filter=Q(operation_type='CASH_FOR_USDT')),  # Damos USD por USDT
            
            # Bolívares que entran
            bs_in=Sum('amount_in', filter=Q(operation_type__in=['SELL_USD_FOR_BS', 'USDT_FOR_BS'])),  # Recibimos BS por venta
            
            # Bolívares que salen
            bs_out=Sum('amount_in', filter=Q(operation_type='BUY_USD_FOR_BS')),  # Damos BS por compra USD
            
            # USDT que entra
            usdt_in=Sum('amount_out', filter=Q(operation_type='CASH_FOR_USDT')),  # Recibimos USDT por USD
            
            # USDT que sale
            usdt_out=Sum('amount_primary', filter=Q(operation_type__in=['USDT_FOR_CASH', 'USDT_FOR_BS'])),  # Damos USDT
            
            # Zelle que sale
            zelle_out=Sum('amount_primary', filter=Q(operation_type='ZELLE_FOR_CASH'))  # Damos Zelle
        )
        volume = {
            'usd_in': (raw_volume['usd_in_buy'] or 0) + (raw_volume['usd_in_commission'] or 0),
            'usd_out': (raw_volume['usd_out_sell'] or 0) + (raw_volume['usd_out_commission'] or 0),
            'bs_in': raw_volume['bs_in'] or 0, 'bs_out': raw_volume['bs_out'] or 0,
            'usdt_in': raw_volume['usdt_in'] or 0, 'usdt_out': raw_volume['usdt_out'] or 0,
            'zelle_out': raw_volume['zelle_out'] or 0
        }

        # --- 4. CÁLCULOS DE GANANCIA USANDO NUEVOS CAMPOS MEJORADOS ---
        # Ganancias por tipo usando los nuevos campos de equivalencia
        profit_summary = transactions_qs.aggregate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            count=Count('id')
        )
        
        summary = {
            'total_transactions': profit_summary['count'] or 0,
            'total_profit_usd': profit_summary['total_profit_usd'] or Decimal('0.00'),
            'total_profit_bs': profit_summary['total_profit_bs'] or Decimal('0.00'),
            'volume': volume
        }

        # --- 5. PAGINACIÓN ---
        paginator = Paginator(transactions_qs.order_by('-created_at'), 25)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        # --- 6. CONTEXTO FINAL ---
        context = {
            'page_title': 'Reporte por Cliente',
            'transactions': page_obj,
            'is_paginated': True,
            'page_obj': page_obj,
            'clients': all_clients,
            'summary': summary,
            'start_date': start_date,
            'end_date': end_date,
            'selected_client_id': int(selected_client_id) if selected_client_id.isdigit() else None,
        }
        
        return render(request, self.template_name, context)
    

# ==============================================================================
class SessionManagementView(LoginRequiredMixin, AdminVerifiedMixin, View):
    template_name = 'exchange/session_management.html'

    def get(self, request, *args, **kwargs):
        vaults = CashVault.objects.all()
        # Obtenemos las sesiones activas para cada bóveda
        active_sessions = {s.vault_id: s for s in VaultSession.objects.filter(status='open')}
        
        context = {
            'vaults': vaults,
            'active_sessions': active_sessions,
        }
        return render(request, self.template_name, context)
    

class AdvancedTransactionCreateView(LoginRequiredMixin, CreateView):
    model = AdvancedTransaction
    form_class = AdvancedTransactionForm
    template_name = 'exchange/advanced_transaction_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        context['page_title'] = f"Nueva Operación Individual para {client.name}"
        context['cancel_url'] = reverse_lazy('client-detail', kwargs={'pk': client.pk})
        return context

    def form_valid(self, form):
        # 1. Obtenemos el objeto sin guardarlo en la BD
        self.object = form.save(commit=False)
        
        # 2. Asignamos los datos que no vienen del formulario
        self.object.client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        self.object.operator = self.request.user
        
        # 3. Guardamos. El método save() del modelo se encargará de los cálculos
        #    basados en la Tasa de Costo si se proveyó.
        self.object.save()
        
        messages.success(self.request, "Operación individual registrada exitosamente.")
        # La llamada a super() se encarga de la redirección
        return super().form_valid(form)

    def get_success_url(self):
        # Volvemos al detalle del cliente después de crear la transacción.
        return reverse_lazy('client-detail', kwargs={'pk': self.kwargs['client_pk']})
# ==============================================================================
# VISTAS DE GESTIÓN DE BÓVEDAS (CAJAS)
# ==============================================================================

class VaultManagementView(LoginRequiredMixin, AdminRequiredMixin, View):
    """
    Vista principal para gestionar la apertura y cierre de todas las bóvedas.
    """
    template_name = 'exchange/vault_management.html'

    def get(self, request, *args, **kwargs):
        vaults = CashVault.objects.all()
        # Creamos un diccionario para buscar fácilmente la sesión activa de cada bóveda
        active_sessions = {s.vault_id: s for s in VaultSession.objects.filter(status='open')}
        
        # Verificamos para cada bóveda si ya se operó hoy
        sessions_today = {
            s.vault_id: s for s in VaultSession.objects.filter(date=timezone.localdate())
        }

        context = {
            'page_title': 'Gestión de Cajas',
            'vaults': vaults,
            'active_sessions': active_sessions,
            'sessions_today': sessions_today,
        }
        return render(request, self.template_name, context)

@admin_required
def open_vault_session(request, vault_id):
    """
    Procesa la apertura de una sesión para una bóveda específica.
    """
    if request.method == 'POST':
        vault = get_object_or_404(CashVault, pk=vault_id)

        # Validaciones
        if VaultSession.objects.filter(vault=vault, status='open').exists():
            messages.error(request, f'La caja "{vault.name}" ya tiene una sesión abierta.')
            return redirect('vault-management')
        if VaultSession.objects.filter(vault=vault, date=timezone.localdate()).exists():
            messages.error(request, f'La caja "{vault.name}" ya fue operada hoy.')
            return redirect('vault-management')

        # Obtener montos del formulario
        try:
            opening_usd = float(request.POST.get('opening_balance_usd', 0))
            opening_bs = float(request.POST.get('opening_balance_bs', 0))
            opening_usdt = float(request.POST.get('opening_balance_usdt', 0))
            opening_zelle = float(request.POST.get('opening_balance_zelle', 0))
        except (ValueError, TypeError):
            messages.error(request, 'Por favor, ingrese montos válidos.')
            return redirect('vault-management')

        # 1. Creamos la nueva sesión
        VaultSession.objects.create(
            vault=vault,
            date=timezone.localdate(),
            status='open',
            opening_balance_usd=opening_usd,
            opening_balance_bs=opening_bs,
            opening_balance_usdt=opening_usdt,
            opening_balance_zelle=opening_zelle,
            opened_by=request.user,
            opened_at=timezone.now()
        )
        
        # 2. Actualizamos la bóveda con los saldos iniciales
        vault.balance_usd = opening_usd
        vault.balance_bs = opening_bs
        vault.balance_usdt = opening_usdt
        vault.balance_zelle = opening_zelle
        vault.save()
        
        messages.success(request, f'Caja "{vault.name}" abierta exitosamente.')
    return redirect('vault-management')

@admin_required
def close_vault_session(request, vault_id):
    """
    Procesa el cierre de una sesión para una bóveda específica.
    """
    if request.method == 'POST':
        vault = get_object_or_404(CashVault, pk=vault_id)
        active_session = VaultSession.objects.filter(vault=vault, status='open').first()

        if not active_session:
            messages.error(request, f'No hay sesión abierta para la caja "{vault.name}".')
            return redirect('vault-management')
            
        # 1. Guardamos los saldos de cierre en la sesión histórica
        active_session.closing_balance_usd = vault.balance_usd
        active_session.closing_balance_bs = vault.balance_bs
        active_session.closing_balance_usdt = vault.balance_usdt
        active_session.closing_balance_zelle = vault.balance_zelle
        
        # Aquí iría la lógica para calcular los totales del día
        # ...
        
        active_session.status = 'closed'
        active_session.closed_by = request.user
        active_session.closed_at = timezone.now()
        active_session.save()
        
        messages.success(request, f'Caja "{vault.name}" cerrada exitosamente.')
    return redirect('vault-management')  


# ==============================================================================
# VISTAS PARA TRANSACCIONES AVANZADAS
# ==============================================================================



@method_decorator(admin_required, name='dispatch')
class AdvancedTransactionUpdateView(LoginRequiredMixin, AdminVerifiedMixin, UpdateView):
    model = AdvancedTransaction
    form_class = AdvancedTransactionForm
    template_name = 'exchange/advanced_transaction_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Editar Operación #{self.object.id}'
        context['cancel_url'] = reverse_lazy('client-detail', kwargs={'pk': self.object.client.pk})
        return context

    def get_success_url(self):
        messages.success(self.request, f"Operación #{self.object.id} actualizada exitosamente.")
        return reverse_lazy('client-detail', kwargs={'pk': self.object.client.pk})


@method_decorator(admin_required, name='dispatch')
class AdvancedTransactionDeleteView(LoginRequiredMixin, AdminVerifiedMixin, DeleteView):
    model = AdvancedTransaction
    template_name = 'exchange/advanced_transaction_confirm_delete.html'
    context_object_name = 'transaction'

    def get_success_url(self):
        messages.success(self.request, f"Operación #{self.object.id} eliminada exitosamente.")
        return reverse_lazy('client-detail', kwargs={'pk': self.object.client.pk})


# VISTA PARA ANULAR UNA OPERACIÓN
@method_decorator(admin_required, name='dispatch')
class AdvancedTransactionCancelView(LoginRequiredMixin, AdminVerifiedMixin, UpdateView):
    model = AdvancedTransaction
    template_name = 'exchange/advanced_transaction_confirm_cancel.html'
    # No necesitamos campos de formulario, la acción es fija.
    fields = [] 
    context_object_name = 'transaction'

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        self.object.operator = self.request.user
        # Ya no calculamos nada aquí, el modelo lo hará solo
        self.object.save()
        return super().form_valid(form)
        

    def get_success_url(self):
        # Volvemos al detalle del cliente
        return reverse_lazy('client-detail', kwargs={'pk': self.object.client.pk})
    

# ==============================================================================
# VISTAS DE EXPORTACIÓN
# ==============================================================================

@login_required
@admin_required
def export_general_report_csv(request):
    """
    Genera y devuelve un archivo CSV con los datos del reporte general,
    respetando los filtros de fecha y operación.
    """
    # 1. Obtenemos los mismos filtros que en el reporte general
    today = timezone.localdate()
    start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
    end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
    operation_filter = request.GET.get('operation_type', '')

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    # 2. Aplicamos los mismos filtros al queryset
    transactions_qs = AdvancedTransaction.objects.filter(
        status='completed',
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    ).select_related('client', 'operator').order_by('created_at')

    if operation_filter:
        transactions_qs = transactions_qs.filter(operation_type=operation_filter)

    # 3. Preparamos la respuesta HTTP
    response = HttpResponse(
        content_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="reporte_general_{start_date_str}_a_{end_date_str}.csv"'},
    )
    response.write(u'\ufeff'.encode('utf8')) # BOM para que Excel reconozca UTF-8

    # 4. Creamos el escritor de CSV y escribimos las filas
    writer = csv.writer(response)
    
    # Escribimos la fila de encabezados
    writer.writerow([
        'ID Transacción', 'Fecha', 'Hora', 'Cliente', 'Operador', 
        'Tipo de Operación', 'Entrada', 'Tasa/Fee', 'Salida', 'Ganancia ($)'
    ])
    
    # Escribimos los datos de cada transacción
    for tx in transactions_qs:
        writer.writerow([
            tx.id,
            tx.created_at.strftime('%Y-%m-%d'),
            tx.created_at.strftime('%H:%M:%S'),
            tx.client.name,
            tx.operator.username if tx.operator else 'N/A',
            tx.get_operation_type_display(),
            tx.amount_in,
            tx.rate_or_fee,
            tx.amount_out,
            tx.profit
        ])
        
    return response



class WorkSheetView(LoginRequiredMixin, View):
    template_name = 'exchange/worksheet.html'
    
    def get(self, request, client_pk):
        client = get_object_or_404(Client, pk=client_pk)
        # Obtiene o crea la hoja de trabajo para el cliente y el día de hoy
        worksheet, created = ClientWorkSheet.objects.get_or_create(
            client=client, 
            date=timezone.now().date(),
            defaults={'status': 'open'} # Solo pone 'open' si es nueva
        )
        
        # Obtenemos las transacciones ya asociadas a esta hoja
        transactions = worksheet.transactions.order_by('-created_at')
        form = AdvancedTransactionForm() # Un formulario vacío para añadir nuevas
        
        context = {
            'client': client,
            'worksheet': worksheet,
            'transactions': transactions,
            'form': form,
        }
        return render(request, self.template_name, context)
    


@admin_required
def reopen_vault_session(request, session_id):
    """
    Procesa la reapertura de una sesión de bóveda que ya fue cerrada en el mismo día.
    """
    if request.method == 'POST':
        session_to_reopen = get_object_or_404(VaultSession, pk=session_id, date=timezone.localdate())
        vault = session_to_reopen.vault

        # Validaciones de seguridad
        if session_to_reopen.status == 'open':
            messages.warning(request, f'La caja "{vault.name}" ya está abierta.')
            return redirect('vault-management')
        if VaultSession.objects.filter(vault=vault, status='open').exists():
            messages.error(request, f'No se puede reabrir. Ya hay otra sesión activa para la caja "{vault.name}".')
            return redirect('vault-management')

        # 1. Restauramos los saldos en la bóveda principal
        vault.balance_usd = session_to_reopen.closing_balance_usd
        vault.balance_bs = session_to_reopen.closing_balance_bs
        vault.balance_usdt = session_to_reopen.closing_balance_usdt
        vault.balance_zelle = session_to_reopen.closing_balance_zelle
        vault.save()
        
        # 2. Reabrimos la sesión
        session_to_reopen.status = 'open'
        session_to_reopen.closed_by = None
        session_to_reopen.closed_at = None
        session_to_reopen.save()
        
        messages.success(request, f'Caja "{vault.name}" reabierta exitosamente.')
    return redirect('vault-management')


class WorkSheetView(LoginRequiredMixin, View):
    """
    Muestra la interfaz principal de la Hoja de Trabajo de un cliente.
    """
    template_name = 'exchange/worksheet.html'
    
    def get(self, request, client_pk):
        client = get_object_or_404(Client, pk=client_pk)
        worksheet, created = ClientWorkSheet.objects.get_or_create(
            client=client, 
            date=timezone.now().date(),
            defaults={'status': 'open'}
        )
        
        # Si la hoja ya estaba cerrada, no permitir añadir más operaciones
        if worksheet.status == 'closed':
            messages.warning(request, f"La hoja de trabajo para este cliente en esta fecha ya está cerrada.")
        
        transactions = worksheet.transactions.order_by('-created_at')
        form = AdvancedTransactionForm()
        
        context = {
            'page_title': f"Hoja de Trabajo - {client.name}",
            'client': client,
            'worksheet': worksheet,
            'transactions': transactions,
            'form': form,
        }
        return render(request, self.template_name, context)

@login_required
def add_transaction_to_worksheet_ajax(request, worksheet_id):
    worksheet = get_object_or_404(ClientWorkSheet, pk=worksheet_id)
    if request.method != 'POST' or worksheet.status != 'open':
        return JsonResponse({'success': False, 'error': 'Invalid request'})

    form = AdvancedTransactionForm(request.POST)
    if form.is_valid():
        tx = form.save(commit=False)
        tx.client = worksheet.client
        tx.operator = request.user
        tx.worksheet = worksheet
        
        # Guardamos la transacción. El método save() del modelo se encarga de los cálculos
        # de amount_out y de profit (si hay tasa base).
        tx.save()

        # Preparamos la respuesta JSON para actualizar la tabla dinámicamente
        new_row_html = render_to_string('exchange/partials/worksheet_transaction_row.html', {'tx': tx})
        
        return JsonResponse({
            'success': True, 
            'new_row_html': new_row_html
        })
    else:
        return JsonResponse({'success': False, 'errors': form.errors})

# exchange/views.py

@login_required
def close_worksheet(request, worksheet_id):
    worksheet = get_object_or_404(ClientWorkSheet, pk=worksheet_id)
    if request.method == 'POST':
        try:
            conversion_rate = Decimal(request.POST.get('conversion_rate', '0'))
            if conversion_rate <= 0:
                raise ValueError("La tasa de conversión debe ser un número positivo.")
        except (ValueError, TypeError):
            messages.error(request, "Tasa de conversión inválida.")
            return redirect('client-worksheet', client_pk=worksheet.client.pk)

        transactions_in_worksheet = worksheet.transactions.all()
        
        # Contadores mejorados para diferentes tipos de ganancias
        summary = {
            'total_profit_usd_spread': Decimal('0.00'),
            'total_profit_bs_spread': Decimal('0.00'),
            'total_profit_usd_commission': Decimal('0.00'),
            'total_profit_bs_commission': Decimal('0.00'),
            'transactions_updated': 0,
        }
        
        with transaction.atomic():  # Asegura que todos los guardados se hagan o ninguno
            for tx in transactions_in_worksheet:
                original_profit = tx.profit
                
                # Asignar la tasa base para el cálculo
                tx.base_rate = conversion_rate
                
                # Usar el método save() mejorado del modelo que calcula todo automáticamente
                tx.save()
                
                # Acumular los totales usando los nuevos campos equivalentes
                if tx.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']:
                    # Ganancias por spread
                    summary['total_profit_usd_spread'] += tx.profit_usd_equivalent or Decimal('0.00')
                    summary['total_profit_bs_spread'] += tx.profit_bs_equivalent or Decimal('0.00')
                elif tx.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
                    # Ganancias por comisión
                    summary['total_profit_usd_commission'] += tx.profit_usd_equivalent or Decimal('0.00')
                    summary['total_profit_bs_commission'] += tx.profit_bs_equivalent or Decimal('0.00')
                
                if tx.profit != original_profit:
                    summary['transactions_updated'] += 1
        
        # Cerrar la hoja de trabajo
        worksheet.status = 'closed'
        worksheet.closed_at = timezone.now()
        worksheet.save()
        
        # --- Mensaje de Resumen Mejorado ---
        # Calculamos totales usando las equivalencias ya calculadas
        total_profit_usd_all = (
            summary['total_profit_usd_spread'] + summary['total_profit_usd_commission']
        )
        total_profit_bs_all = (
            summary['total_profit_bs_spread'] + summary['total_profit_bs_commission']
        )
        
        # Calculamos flujo neto de caja usando lógica mejorada
        net_flow = {'usd': Decimal('0'), 'bs': Decimal('0'), 'usdt': Decimal('0'), 'zelle': Decimal('0')}
        flow_map = {
            'SELL_USD_FOR_BS': {'usd': -1, 'bs': 1},
            'BUY_USD_FOR_BS': {'usd': 1, 'bs': -1},
            'USDT_FOR_CASH': {'usdt': -1, 'usd': 1},
            'CASH_FOR_USDT': {'usd': -1, 'usdt': 1},
            'USDT_FOR_BS': {'usdt': -1, 'bs': 1},
            'ZELLE_FOR_CASH': {'zelle': -1, 'usd': 1},
        }
        
        for tx in transactions_in_worksheet:
            flow = flow_map.get(tx.operation_type, {})
            for currency, multiplier in flow.items():
                if currency in ['usd', 'usdt', 'zelle']:
                    net_flow[currency] += (tx.amount_in if multiplier < 0 else tx.amount_out) * multiplier
                else:  # bs
                    net_flow[currency] += (tx.amount_out if multiplier > 0 else tx.amount_in) * abs(multiplier)

        # Generar mensaje de resumen más informativo
        summary_message = (
            f"<strong>📊 Resumen de Cierre - Hoja de Trabajo</strong><br><br>"
            f"<strong>💰 Ganancias por Tipo:</strong><br>"
            f"• Por Spread: ${summary['total_profit_usd_spread']:,.2f} / {summary['total_profit_bs_spread']:,.2f} BS<br>"
            f"• Por Comisión: ${summary['total_profit_usd_commission']:,.2f} / {summary['total_profit_bs_commission']:,.2f} BS<br><br>"
            f"<strong class='text-success'>🎯 Total Consolidado: ${total_profit_usd_all:,.2f} / {total_profit_bs_all:,.2f} BS</strong><br><br>"
            f"<strong>📈 Flujo Neto de Caja:</strong><br>"
            f"• USD: {net_flow['usd']:+,.2f} | BS: {net_flow['bs']:+,.2f}<br>"
            f"• USDT: {net_flow['usdt']:+,.2f} | Zelle: {net_flow['zelle']:+,.2f}<br><br>"
            f"<small>Transacciones procesadas: {summary['transactions_updated']} de {transactions_in_worksheet.count()}</small>"
        )
        messages.info(request, summary_message, extra_tags='safe')
        
        return redirect('client-detail', pk=worksheet.client.pk)
    
    return redirect('client-list')


@method_decorator(admin_required, name='dispatch')
class VaultAdjustmentView(LoginRequiredMixin, AdminVerifiedMixin, CreateView):
    model = VaultAdjustment
    form_class = VaultAdjustmentForm
    template_name = 'exchange/vault_adjustment_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vault = get_object_or_404(CashVault, pk=self.kwargs['vault_id'])
        context['page_title'] = f"Ajuste de Emergencia para: {vault.name}"
        context['vault'] = vault
        return context

    def form_valid(self, form):
        vault = get_object_or_404(CashVault, pk=self.kwargs['vault_id'])
        
        # Guardamos el registro de auditoría
        adjustment = form.save(commit=False)
        adjustment.vault = vault
        adjustment.user = self.request.user
        adjustment.save()
        
        # Aplicamos los cambios al saldo de la bóveda
        vault.balance_usd += adjustment.amount_usd
        vault.balance_bs += adjustment.amount_bs
        vault.balance_usdt += adjustment.amount_usdt
        vault.balance_zelle += adjustment.amount_zelle
        vault.save()
        
        messages.success(self.request, f"Ajuste en la caja '{vault.name}' realizado exitosamente.")
        return redirect('vault-management')
    
@login_required
def reopen_worksheet(request, worksheet_id):
    """
    Reabre una hoja de trabajo que fue cerrada en el mismo día.
    """
    if request.method == 'POST':
        worksheet_to_reopen = get_object_or_404(
            ClientWorkSheet, pk=worksheet_id, date=timezone.now().date()
        )

        if worksheet_to_reopen.status == 'open':
            messages.warning(request, "Esta hoja de trabajo ya está abierta.")
        else:
            worksheet_to_reopen.status = 'open'
            worksheet_to_reopen.closed_at = None
            worksheet_to_reopen.save(update_fields=['status', 'closed_at'])
            messages.success(request, f"Hoja de trabajo para {worksheet_to_reopen.client.name} reabierta exitosamente.")
        
        return redirect('client-worksheet', client_pk=worksheet_to_reopen.client.pk)
    return redirect('client-list')   



@login_required
def update_transaction_status_ajax(request, pk):
    """
    Actualiza el estado de una transacción vía AJAX y devuelve
    la información necesaria para actualizar la UI.
    """
    if request.method == 'POST':
        transaction = get_object_or_404(AdvancedTransaction, pk=pk)
        new_status = request.POST.get('status')
        
        if new_status not in [choice[0] for choice in AdvancedTransaction.STATUS_CHOICES]:
            return JsonResponse({'success': False, 'error': 'Estado no válido.'})
            
        transaction.status = new_status
        # Guardar solo el campo de estado para eficiencia.
        # Esto disparará la señal post_save si el estado cambia a 'completed'.
        transaction.save(update_fields=['status'])
        
        # Mapeo de estados a clases de Bootstrap para los badges
        status_styles = {
            'pending': {'class': 'bg-warning text-dark', 'text': 'Pendiente'},
            'completed': {'class': 'bg-success', 'text': 'Completada'},
            'cancelled': {'class': 'bg-secondary', 'text': 'Anulada'},
        }
        style_info = status_styles.get(new_status, {'class': 'bg-light', 'text': new_status})
        
        return JsonResponse({
            'success': True, 
            'new_status_text': style_info['text'],
            'new_status_class': style_info['class'],
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})



class PendingTransactionsReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/pending_transactions_report.html'
    
    def get(self, request, *args, **kwargs):
        # Filtramos por fecha. Por defecto, muestra las de hoy.
        report_date_str = request.GET.get('date', timezone.now().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
        
        pending_transactions = AdvancedTransaction.objects.filter(
            status='pending',
            created_at__date=report_date
        ).order_by('client__name', 'created_at')

        context = {
            'page_title': f"Reporte de Operaciones Pendientes - {report_date.strftime('%d/%m/%Y')}",
            'transactions': pending_transactions,
            'report_date': report_date,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        # --- LÓGICA DE ENVÍO DE CORREO ---
        report_date_str = request.POST.get('date')
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
        
        # Obtenemos los correos del formulario, los separamos por coma y limpiamos espacios
        emails_str = request.POST.get('emails', '')
        recipient_list = [email.strip() for email in emails_str.split(',') if email.strip()]

        if not recipient_list:
            messages.error(request, "Por favor, ingrese al menos una dirección de correo electrónico.")
            return redirect(request.path_info + f'?date={report_date_str}')

        # Obtenemos los datos para el reporte
        pending_transactions = AdvancedTransaction.objects.filter(
            status='pending',
            created_at__date=report_date
        ).order_by('client__name', 'created_at')

        # Preparamos el contexto para la plantilla de correo
        email_context = {
            'report_date': report_date,
            'transactions': pending_transactions,
        }

        # Renderizamos la plantilla HTML del correo a un string
        html_content = render_to_string('emails/pending_transactions_email.html', email_context)
        # Creamos una versión en texto plano para clientes de correo que no soportan HTML
        text_content = strip_tags(html_content)
        
        # Creamos y enviamos el correo
        subject = f"Reporte de Operaciones Pendientes - {report_date.strftime('%d/%m/%Y')}"
        from_email = 'reportes@traderapp.com' # Puedes cambiar esto
        
        try:
            msg = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
            msg.attach_alternative(html_content, "text/html")
            msg.send()
            messages.success(request, f"Reporte enviado exitosamente a: {', '.join(recipient_list)}")
        except Exception as e:
            messages.error(request, f"Ocurrió un error al enviar el correo: {e}")
            
        return redirect(request.path_info + f'?date={report_date_str}')
    


# ... (mantén tus imports y otras vistas) ...

class ProfitReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/profit_report.html'

    def get(self, request, *args, **kwargs):
        # --- 1. PROCESAR FILTROS ---
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        operation_filter = request.GET.get('operation_type', '')

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        # --- 2. QUERYSET BASE ---
        # Filtramos transacciones completadas Y que tengan una ganancia registrada usando los nuevos campos
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).filter(
            Q(profit_usd_equivalent__gt=0) | Q(profit_bs_equivalent__gt=0)
        ).select_related('client', 'operator')

        if operation_filter:
            transactions_qs = transactions_qs.filter(operation_type=operation_filter)

        # --- 3. CÁLCULOS DE RESUMEN DE GANANCIAS USANDO NUEVOS CAMPOS ---
        # Ganancias por comisión usando los nuevos campos equivalentes
        profit_by_commission = transactions_qs.filter(
            operation_type__in=['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
        ).aggregate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent')
        )
        
        # Ganancias por spread usando los nuevos campos equivalentes
        profit_by_spread = transactions_qs.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent')
        )
        
        # Totales consolidados
        profit_from_fees_usd = profit_by_commission['total_profit_usd'] or Decimal('0.00')
        profit_from_spread_bs = profit_by_spread['total_profit_bs'] or Decimal('0.00')

        # --- 4. PAGINACIÓN ---
        paginator = Paginator(transactions_qs.order_by('-created_at'), 25)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        # --- 5. CONTEXTO ---
        context = {
            'page_title': 'Reporte Detallado de Ganancias',
            'transactions': page_obj,
            'is_paginated': True,
            'page_obj': page_obj,
            'start_date': start_date,
            'end_date': end_date,
            'summary': {
                'profit_from_spread_bs': profit_from_spread_bs,
                'profit_from_fees_usd': profit_from_fees_usd,
            },
            'operation_choices': AdvancedTransaction.OPERATION_CHOICES,
            'selected_operation': operation_filter,
        }
        
        return render(request, self.template_name, context)
    

# ==============================================================================
# GESTIÓN DE CIERRE DE HOJAS DE TRABAJO POR LOTE
# ==============================================================================

class BatchWorksheetCloseView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/batch_worksheet_close.html'
    
    def get(self, request, *args, **kwargs):
        # Obtener todas las hojas de trabajo abiertas ordenadas por fecha
        open_worksheets = ClientWorkSheet.objects.filter(
            status='open'
        ).select_related('client').order_by('-date')
        
        # Agrupar por fecha para facilitar la selección por lotes
        worksheets_by_date = {}
        for ws in open_worksheets:
            date_str = ws.date.strftime('%Y-%m-%d')
            if date_str not in worksheets_by_date:
                worksheets_by_date[date_str] = []
            worksheets_by_date[date_str].append(ws)
        
        # Convertir a lista ordenada para el template
        worksheets_grouped = []
        for date_str, worksheets in sorted(worksheets_by_date.items(), reverse=True):
            worksheets_grouped.append({
                'date': date_str,
                'date_display': datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y'),
                'worksheets': worksheets,
                'count': len(worksheets)
            })
        
        context = {
            'page_title': 'Cierre Masivo de Hojas de Trabajo',
            'worksheets_grouped': worksheets_grouped,
            'total_open_worksheets': open_worksheets.count(),
        }
        return render(request, self.template_name, context)
    
    def post(self, request, *args, **kwargs):
        # Obtener la tasa de conversión base para todas las hojas
        try:
            conversion_rate = Decimal(request.POST.get('conversion_rate', '0'))
            if conversion_rate <= 0:
                raise ValueError("La tasa de conversión debe ser un número positivo.")
        except (ValueError, TypeError):
            messages.error(request, "Tasa de conversión inválida. Por favor ingrese un valor positivo.")
            return redirect('batch-worksheet-close')
        
        # Obtener los IDs de las hojas de trabajo seleccionadas
        selected_worksheets = request.POST.getlist('selected_worksheets')
        
        if not selected_worksheets:
            messages.warning(request, "No se seleccionaron hojas de trabajo para cerrar.")
            return redirect('batch-worksheet-close')
        
        # Preparar contadores para el resumen
        summary = {
            'worksheets_closed': 0,
            'transactions_updated': 0,
            'total_profit_usd': Decimal('0.00'),
            'total_profit_bs': Decimal('0.00'),
            'error_count': 0,
        }
        
        # Procesar cada hoja de trabajo en una transacción atómica grande
        with transaction.atomic():
            for ws_id in selected_worksheets:
                try:
                    worksheet = ClientWorkSheet.objects.get(pk=ws_id, status='open')
                    transactions = worksheet.transactions.all()
                    
                    # Procesar cada transacción en la hoja
                    for tx in transactions:
                        tx.base_rate = conversion_rate
                        tx.save() # Este save() activa el cálculo mejorado
                        
                        # Acumular ganancias
                        summary['total_profit_usd'] += tx.profit_usd_equivalent or Decimal('0.00')
                        summary['total_profit_bs'] += tx.profit_bs_equivalent or Decimal('0.00')
                        summary['transactions_updated'] += 1
                    
                    # Cerrar la hoja de trabajo
                    worksheet.status = 'closed'
                    worksheet.closed_at = timezone.now()
                    worksheet.save()
                    summary['worksheets_closed'] += 1
                    
                except Exception as e:
                    summary['error_count'] += 1
                    # Continuar con la siguiente hoja en caso de error
                    continue
        
        # Mostrar mensaje de resumen
        if summary['worksheets_closed'] > 0:
            summary_message = (
                f"<strong>✅ Cierre masivo completado</strong><br><br>"
                f"<strong>📋 Resumen:</strong><br>"
                f"• Hojas cerradas: {summary['worksheets_closed']} de {len(selected_worksheets)}<br>"
                f"• Transacciones procesadas: {summary['transactions_updated']}<br>"
                f"• Ganancia total USD: ${summary['total_profit_usd']:,.2f}<br>"
                f"• Ganancia total BS: {summary['total_profit_bs']:,.2f} Bs<br>"
            )
            if summary['error_count'] > 0:
                summary_message += f"<br><strong class='text-warning'>⚠️ Advertencia:</strong> {summary['error_count']} hojas de trabajo no pudieron ser procesadas."
            
            messages.success(request, summary_message, extra_tags='safe')
        else:
            messages.error(request, "No se pudo cerrar ninguna hoja de trabajo. Por favor, intente nuevamente.")
        
        return redirect('batch-worksheet-close')


@login_required
@admin_required
def batch_reopen_worksheets(request):
    """Función para reabrir múltiples hojas de trabajo que fueron cerradas hoy"""
    if request.method == 'POST':
        # Obtener las hojas seleccionadas
        selected_worksheets = request.POST.getlist('selected_worksheets')
        today = timezone.now().date()
        
        if not selected_worksheets:
            messages.warning(request, "No se seleccionaron hojas de trabajo para reabrir.")
            return redirect('batch-worksheet-close')
        
        # Contar hojas procesadas
        reopened_count = 0
        error_count = 0
        
        # Reabrir cada hoja
        for ws_id in selected_worksheets:
            try:
                worksheet = ClientWorkSheet.objects.get(pk=ws_id, status='closed', date=today)
                worksheet.status = 'open'
                worksheet.closed_at = None
                worksheet.save(update_fields=['status', 'closed_at'])
                reopened_count += 1
            except Exception:
                error_count += 1
                continue
        
        # Mostrar mensaje de éxito
        if reopened_count > 0:
            messages.success(
                request, 
                f"Se reabrieron {reopened_count} hojas de trabajo exitosamente. "
                f"{error_count} hojas no pudieron ser procesadas."
            )
        else:
            messages.error(
                request, 
                "No se pudo reabrir ninguna hoja de trabajo. "
                "Recuerde que solo se pueden reabrir hojas cerradas en la fecha actual."
            )
    
    return redirect('batch-worksheet-close')

# ==============================================================================
# VISTAS DE ADMINISTRACIÓN AVANZADA
# ==============================================================================

class ResetDataView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/reset_data.html'
    form_class = ResetDataForm

    def get(self, request, *args, **kwargs):
        form = self.form_class()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            password = form.cleaned_data['password']
            
            # Verificamos la contraseña del superusuario que está ejecutando la acción
            user = authenticate(username=request.user.username, password=password)
            if user is not None and user.is_superuser:
                # --- LÓGICA DE BORRADO ---
                try:
                    # Orden de borrado: de lo más dependiente a lo menos
                    AdvancedTransaction.objects.all().delete()
                    VaultSession.objects.all().delete()
                    ClientWorkSheet.objects.all().delete()
                    Client.objects.all().delete()
                    
                    # Reseteamos los saldos de las bóvedas a cero
                    CashVault.objects.all().update(
                        balance_usd=0, balance_bs=0, balance_usdt=0, balance_zelle=0
                    )
                    
                    messages.success(request, "¡Reseteo completado! Todos los datos transaccionales han sido eliminados.")
                    return redirect('dashboard')

                except Exception as e:
                    messages.error(request, f"Ocurrió un error inesperado durante el reseteo: {e}")

            else:
                messages.error(request, "Contraseña incorrecta. La acción de reseteo ha sido cancelada.")
        
        return render(request, self.template_name, {'form': form})


