# exchange/views.py

from django import forms
from django.db.models import Sum, Count
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
    template_name = 'exchange/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Dashboard Principal'

        # --- SALDOS DE CAJA ---
        # Obtenemos los saldos de todas las bóvedas y los sumamos
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

        # --- CUENTAS POR COBRAR Y PAGAR (PENDIENTES) ---
        pending_tx = AdvancedTransaction.objects.filter(status='pending')
        
        # Total a recibir en BS
        context['total_receivable_bs'] = pending_tx.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(total=Sum('amount_out'))['total'] or 0.00
        
        # Total a recibir en "dólares" (agrupamos USD, USDT, Zelle)
        context['total_receivable_usd'] = (
            pending_tx.filter(operation_type__in=['BUY_USD_FOR_BS', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']).aggregate(total=Sum('amount_in'))['total'] or 0.00
        )

        # Total a pagar en BS
        context['total_payable_bs'] = (
            pending_tx.filter(operation_type='BUY_USD_FOR_BS').aggregate(total=Sum('amount_out'))['total'] or 0.00
        )

        # Total a pagar en "dólares"
        payable_usd = pending_tx.filter(operation_type='SELL_USD_FOR_BS').aggregate(total=Sum('amount_in'))['total'] or Decimal('0.00')
        payable_usdt = pending_tx.filter(operation_type__in=['USDT_FOR_BS', 'CASH_FOR_USDT']).aggregate(total=Sum('amount_in'))['total'] or Decimal('0.00')
        payable_zelle = pending_tx.filter(operation_type='ZELLE_FOR_CASH').aggregate(total=Sum('amount_in'))['total'] or Decimal('0.00')
        context['total_payable_usd'] = payable_usd + payable_usdt + payable_zelle
        

        # --- LISTAS DE CLIENTES ---
        context['clients_who_owe'] = Client.objects.filter(adv_transactions__status='pending').distinct()
        context['clients_we_owe'] = Client.objects.filter(adv_transactions__status='pending').distinct() # Simplificado, se puede detallar más

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
    template_name = 'exchange/general_report_advanced.html'
    
    def get(self, request, *args, **kwargs):
        # ... (lógica de filtros de fecha y operación sin cambios) ...
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        operation_filter = request.GET.get('operation_type', '')

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('client', 'operator')

        if operation_filter:
            transactions_qs = transactions_qs.filter(operation_type=operation_filter)

        # --- NUEVA LÓGICA DE RESUMEN CONTABLE ---
        
        # Ganancia directa por comisiones (en USD/USDT)
        profit_from_fees = transactions_qs.filter(
            operation_type__in=['USDT_FOR_CASH', 'CASH_FOR_USDT']
        ).aggregate(total=Sum('profit'))['total'] or Decimal('0.00')
        
        # Ingresos en BS (por ventas de USD y USDT)
        income_bs = transactions_qs.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(total=Sum('amount_out'))['total'] or Decimal('0.00')
        
        # Costos en BS (por compras de USD)
        cost_bs = transactions_qs.filter(
            operation_type='BUY_USD_FOR_BS'
        ).aggregate(total=Sum('amount_out'))['total'] or Decimal('0.00')
        
        # Ganancia NETA por Spread Cambiario (en BS)
        profit_from_spread = income_bs - cost_bs
        
        # Para el resumen por tipo, la lógica anterior funciona bien
        summary_by_type = list(transactions_qs
            .values('operation_type')
            .annotate(count=Count('id'), total_in=Sum('amount_in'), total_out=Sum('amount_out'), total_profit=Sum('profit'))
            .order_by('operation_type')
        )
        operation_names = dict(AdvancedTransaction.OPERATION_CHOICES)
        for summary in summary_by_type:
            summary['display_name'] = operation_names.get(summary['operation_type'])

        # --- CONTEXTO FINAL ---
        paginator = Paginator(transactions_qs.order_by('-created_at'), 25)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        context = {
            'page_title': 'Reporte General de Operaciones',
            'transactions': page_obj,
            'is_paginated': True,
            'page_obj': page_obj,
            'start_date': start_date,
            'end_date': end_date,
            'general_summary': { # Diccionario de resumen para las tarjetas
                'total_transactions': transactions_qs.count(),
                'profit_from_spread_bs': profit_from_spread,
                'profit_from_fees_usd': profit_from_fees,
            },
            'summary_by_type': summary_by_type,
            'operation_choices': AdvancedTransaction.OPERATION_CHOICES,
            'selected_operation': operation_filter,
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
        ).select_related('client') # Optimización

        if selected_client_id and selected_client_id.isdigit():
            transactions_qs = transactions_qs.filter(client_id=selected_client_id)
        
        # --- 3. CÁLCULOS DE RESUMEN ---
        summary_data = transactions_qs.aggregate(
            total_transactions=Count('id'),
            total_usd_bought=Sum('amount_in', filter=Q(operation_type='BUY_USD_FOR_BS')),
            total_usd_sold=Sum('amount_in', filter=Q(operation_type='SELL_USD_FOR_BS'))
        )
        
        summary = {
            'total_transactions': summary_data.get('total_transactions') or 0,
            'total_usd_bought': summary_data.get('total_usd_bought') or 0.00,
            'total_usd_sold': summary_data.get('total_usd_sold') or 0.00,
        }

        # --- 4. PAGINACIÓN ---
        paginator = Paginator(transactions_qs.order_by('-created_at'), 25)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        # --- 5. CONTEXTO ---
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
    # ...
    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        self.object.operator = self.request.user
        
        # --- CÁLCULO DE amount_out SE HACE AQUÍ ---
        tx = self.object
        rate_or_fee = Decimal(tx.rate_or_fee)
        amount_in = Decimal(tx.amount_in)
        
        if tx.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']:
            tx.amount_out = amount_in * rate_or_fee
        elif tx.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
            commission = amount_in * (rate_or_fee / Decimal('100'))
            tx.amount_out = amount_in + commission # Tu lógica de prima
        
        self.object.save()
        return super().form_valid(form)
    

    def get_success_url(self):
        # Volvemos al detalle del cliente después de crear la transacción.
        messages.success(self.request, "Operación registrada exitosamente.")
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
        """
        Cuando el formulario (en este caso, un simple botón de confirmación) es enviado,
        cambiamos el estado a 'cancelled'.
        """
        transaction = self.get_object()
        
        # Verificamos que la transacción no esté ya completada para evitar problemas contables
        if transaction.status == 'completed':
            messages.error(self.request, "No se puede anular una operación que ya ha sido completada.")
            return redirect('client-detail', pk=transaction.client.pk)

        transaction.status = 'cancelled'
        transaction.save(update_fields=['status']) # Guardamos solo el campo de estado
        
        messages.success(self.request, f"Operación #{transaction.id} anulada exitosamente.")
        return redirect(self.get_success_url())

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
    """
    Procesa la adición de una nueva transacción a la hoja de trabajo vía AJAX.
    """
    worksheet = get_object_or_404(ClientWorkSheet, pk=worksheet_id)
    if request.method == 'POST' and worksheet.status == 'open':
        form = AdvancedTransactionForm(request.POST)
        if form.is_valid():
            # Creamos la transacción pero no la guardamos en la BD aún
            transaction = form.save(commit=False)
            transaction.client = worksheet.client
            transaction.operator = request.user
            transaction.worksheet = worksheet
            # El método save() del modelo se encarga de los cálculos
            transaction.save()

            # Preparamos la respuesta JSON
            # Renderizamos la nueva fila de la tabla como un string HTML
            new_row_html = render_to_string(
                'exchange/partials/worksheet_transaction_row.html', 
                {'tx': transaction}
            )
            # Obtenemos el resumen actualizado
            summary = worksheet.transactions.aggregate(
                total_in=Sum('amount_in'), total_out=Sum('amount_out')
            )

            return JsonResponse({
                'success': True, 
                'new_row_html': new_row_html,
                'summary': {
                    'total_in': summary.get('total_in') or 0,
                    'total_out': summary.get('total_out') or 0,
                }
            })
        else:
            return JsonResponse({'success': False, 'errors': form.errors})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

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
        
        total_profit_bs_spread = Decimal('0.00')
        total_profit_usd_fees = Decimal('0.00')
        
        with transaction.atomic(): # Asegura que todos los guardados se hagan o ninguno
            for tx in transactions_in_worksheet:
                rate_or_fee = Decimal(tx.rate_or_fee)
                amount_in = Decimal(tx.amount_in)
                
                # Cálculo de ganancia por comisión (en USD/USDT)
                if tx.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
                    tx.profit = amount_in * (rate_or_fee / Decimal('100'))
                    total_profit_usd_fees += tx.profit
                
                # Cálculo de ganancia por spread (en BS)
                elif tx.operation_type == 'SELL_USD_FOR_BS' or tx.operation_type == 'USDT_FOR_BS':
                    tx.profit = (rate_or_fee - conversion_rate) * amount_in
                    total_profit_bs_spread += tx.profit
                
                elif tx.operation_type == 'BUY_USD_FOR_BS':
                    tx.profit = (conversion_rate - rate_or_fee) * amount_in
                    total_profit_bs_spread += tx.profit
                
                else:
                    tx.profit = Decimal('0.00')

                tx.save(update_fields=['profit'])
        
        worksheet.status = 'closed'
        worksheet.closed_at = timezone.now()
        worksheet.save()
        
        # --- Mensaje de Resumen ---
        profit_fees_in_bs = total_profit_usd_fees * conversion_rate
        total_profit_in_bs = total_profit_bs_spread + profit_fees_in_bs
        
        net_flow = { 'usd': Decimal('0'), 'bs': Decimal('0'), 'usdt': Decimal('0'), 'zelle': Decimal('0') }
        for tx in transactions_in_worksheet:
            flows={'SELL_USD_FOR_BS':{'usd':-tx.amount_in,'bs':tx.amount_out},'BUY_USD_FOR_BS':{'usd':tx.amount_in,'bs':-tx.amount_out},'USDT_FOR_CASH':{'usdt':-tx.amount_in,'usd':tx.amount_out},'CASH_FOR_USDT':{'usd':-tx.amount_in,'usdt':tx.amount_out},'USDT_FOR_BS':{'usdt':-tx.amount_in,'bs':tx.amount_out},'ZELLE_FOR_CASH':{'zelle':-tx.amount_in,'usd':tx.amount_out}}
            tx_flow = flows.get(tx.operation_type, {})
            for currency, amount in tx_flow.items(): net_flow[currency] += amount

        summary_message = (
            f"<strong>Resumen de la Sesión:</strong><br>"
            f"Ganancia por Spread: {total_profit_bs_spread:,.2f} BS<br>"
            f"Ganancia por Comisión: ${total_profit_usd_fees:,.2f} (≈{profit_fees_in_bs:,.2f} BS)<br>"
            f"<strong class='text-success'>Ganancia Total Aprox: {total_profit_in_bs:,.2f} Bs.</strong><hr>"
            f"<strong>Flujo Neto de Caja:</strong><br>"
            f"USD: {net_flow['usd']:,.2f} | BS: {net_flow['bs']:,.2f} | USDT: {net_flow['usdt']:,.2f} | Zelle: {net_flow['zelle']:,.2f}"
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
        # Filtramos transacciones completadas Y que tengan una ganancia registrada
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            profit__gt=0,  # <-- Filtro clave: solo transacciones con ganancia > 0
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('client', 'operator')

        if operation_filter:
            transactions_qs = transactions_qs.filter(operation_type=operation_filter)

        # --- 3. CÁLCULOS DE RESUMEN DE GANANCIAS ---
        # Ganancia total por comisiones (en USD/USDT)
        profit_from_fees = transactions_qs.filter(
            operation_type__in=['USDT_FOR_CASH', 'CASH_FOR_USDT']
        ).aggregate(total=Sum('profit'))['total'] or Decimal('0.00')
        
        # Ganancia total por spread (en BS)
        profit_from_spread = transactions_qs.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(total=Sum('profit'))['total'] or Decimal('0.00')

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
                'profit_from_spread_bs': profit_from_spread,
                'profit_from_fees_usd': profit_from_fees,
            },
            'operation_choices': AdvancedTransaction.OPERATION_CHOICES,
            'selected_operation': operation_filter,
        }
        
        return render(request, self.template_name, context)
    

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


