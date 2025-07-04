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
from .models import Client, Transaction, User, CashOnHand, DailySession, CashVault, VaultSession, AdvancedTransaction
from .forms import AdvancedTransactionForm
from django.contrib.auth import authenticate
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from .decorators import admin_required
from decimal import Decimal 

# ==============================================================================
# MIXINS DE AUTORIZACIÓN
# ==============================================================================


class AdminRequiredMixin(UserPassesTestMixin):
    """
    Mixin que permite el acceso solo a usuarios administradores.
    """
    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_staff

    def handle_no_permission(self):
        messages.error(self.request, "No tienes permisos de administrador para acceder a esta página.")
        raise PermissionDenied("No tienes permisos de administrador.")
from django.utils import timezone
from datetime import date
from datetime import datetime, timedelta
from django.db import models 
from django.db.models import Q 







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
    

class AdminPasswordVerifyView(LoginRequiredMixin, View):
    template_name = 'exchange/admin_password_verify.html'
    
    def get(self, request, *args, **kwargs):
        # El 'next_url' nos dice a dónde ir después de una verificación exitosa
        next_url = request.GET.get('next', '/')
        return render(request, self.template_name, {'next_url': next_url})

    def post(self, request, *args, **kwargs):
        password = request.POST.get('password')
        next_url = request.POST.get('next_url', '/')
        
        # Usamos el sistema de autenticación de Django para verificar la contraseña
        user = authenticate(username=request.user.username, password=password)
        
        if user is not None:
            # La contraseña es correcta, guardamos una bandera en la sesión
            # que será válida por un corto tiempo (ej. 5 minutos)
            request.session['admin_verified'] = True
            request.session.set_expiry(300) # La sesión expira en 300 segundos
            messages.success(request, 'Verificación exitosa. Ahora puedes realizar la acción.')
            return redirect(next_url)
        else:
            # La contraseña es incorrecta
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

class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model = Client
    fields = ['name', 'identifier', 'phone', 'email']
    template_name = 'exchange/client_form.html'
    success_url = reverse_lazy('client-list')

class ClientDeleteView(LoginRequiredMixin, DeleteView):
    model = Client
    template_name = 'exchange/client_confirm_delete.html'
    success_url = reverse_lazy('client-list')


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

def exchange_volume_chart_data(request):
    """ API que devuelve el número de transacciones completadas por mes. """
    data = AdvancedTransaction.objects.filter(status='completed') \
        .annotate(month=TruncMonth('created_at')) \
        .values('month') \
        .annotate(count=Count('id')) \
        .order_by('month')
    
    labels = [d['month'].strftime('%B %Y') for d in data]
    values = [d['count'] for d in data]
    
    return JsonResponse({'labels': labels, 'data': values})


def operation_composition_chart_data(request):
    """ API que devuelve la composición de tipos de operación. """
    data = AdvancedTransaction.objects.filter(status='completed') \
        .values('operation_type') \
        .annotate(count=Count('id')) \
        .order_by('operation_type')

    operation_names = dict(AdvancedTransaction.OPERATION_CHOICES)
    labels = [operation_names.get(d['operation_type'], d['operation_type']) for d in data]
    values = [d['count'] for d in data]

    return JsonResponse({'labels': labels, 'data': values})


def monthly_flow_chart_data(request):
    """ API que devuelve el flujo total de USD (efectivo) y USDT movidos por mes. """
    data = AdvancedTransaction.objects.filter(status='completed') \
        .annotate(month=TruncMonth('created_at')) \
        .values('month') \
        .annotate(
            # Suma de USD en operaciones de compra/venta de efectivo
            total_usd_cash=Sum('amount_in', filter=Q(operation_type__in=['BUY_USD_FOR_BS', 'SELL_USD_FOR_BS', 'CASH_FOR_USDT'])),
            # Suma de USDT en operaciones que involucran USDT
            total_usdt=Sum('amount_in', filter=Q(operation_type__in=['USDT_FOR_CASH', 'USDT_FOR_BS', 'CASH_FOR_USDT']))
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
    # Apuntamos al nuevo modelo VaultSession
    model = VaultSession
    template_name = 'exchange/daily_session_report.html'
    context_object_name = 'sessions'
    # Mostramos solo las sesiones cerradas, ordenadas por fecha
    queryset = VaultSession.objects.filter(status='closed').order_by('-date')
    paginate_by = 15



class GeneralReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/general_report_advanced.html' # Usaremos una nueva plantilla para el reporte avanzado
    
    def get(self, request, *args, **kwargs):
        # --- 1. MANEJO DE FILTROS (Fechas y Tipo de Operación) ---
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        operation_filter = request.GET.get('operation_type', '')

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # --- 2. CONSTRUCCIÓN DEL QUERYSET BASE ---
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__gte=start_date,
            created_at__lt=end_date + timedelta(days=1)
        )
        
        if operation_filter:
            transactions_qs = transactions_qs.filter(operation_type=operation_filter)

        # --- 3. CÁLCULOS AGREGADOS EFICIENTES ---
        
        # Resumen general con una sola consulta
        general_summary = transactions_qs.aggregate(
            total_transactions=Count('id'),
            total_profit=Sum('profit')
        )
        
        # Desglose por tipo de operación con una sola consulta
        summary_by_type = list(transactions_qs
            .values('operation_type')
            .annotate(
                count=Count('id'),
                total_in=Sum('amount_in'),
                total_out=Sum('amount_out'),
                total_profit=Sum('profit')
            )
            .order_by('operation_type')
        )

        # Mapear los nombres de operación para la plantilla
        operation_names = dict(AdvancedTransaction.OPERATION_CHOICES)
        for summary in summary_by_type:
            summary['display_name'] = operation_names.get(summary['operation_type'])

        # --- 4. PREPARACIÓN DEL CONTEXTO PARA LA PLANTILLA ---
        context = {
            'page_title': 'Reporte General de Operaciones',
            'transactions': transactions_qs.order_by('-created_at')[:50], # Limitar para no sobrecargar
            'start_date': start_date,
            'end_date': end_date,
            'general_summary': general_summary,
            'summary_by_type': summary_by_type,
            'operation_choices': AdvancedTransaction.OPERATION_CHOICES, # Para el dropdown de filtros
            'selected_operation': operation_filter,
        }
        
        return render(request, self.template_name, context)


class ClientReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'exchange/client_report.html'
    
    def get(self, request, *args, **kwargs):
        # --- 1. OBTENER DATOS PARA LOS FILTROS ---
        all_clients = Client.objects.all().order_by('name') # Obtenemos todos los clientes para el <select>
        
        # --- 2. PROCESAR LOS FILTROS DE LA URL ---
        selected_client_id = request.GET.get('client', '')
        
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # --- 3. CONSTRUIR EL QUERYSET BASE Y APLICAR FILTROS ---
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__gte=start_date,
            created_at__lt=end_date + timedelta(days=1)
        )
        
        if selected_client_id and selected_client_id.isdigit():
            transactions_qs = transactions_qs.filter(client_id=selected_client_id)
        
        # --- 4. CÁLCULOS DE RESUMEN ---
        summary_data = transactions_qs.aggregate(
            total_transactions=Count('id'),
            total_usd_sold=Sum('amount_in', filter=Q(operation_type='SELL_USD_FOR_BS')), # Asumiendo amount_in es USD
            total_usd_bought=Sum('amount_in', filter=Q(operation_type='BUY_USD_FOR_BS')), # Asumiendo amount_in es USD
        )

        summary = {
            'total_transactions': summary_data.get('total_transactions') or 0,
            'total_usd_sold': summary_data.get('total_usd_sold') or 0.00,
            'total_usd_bought': summary_data.get('total_usd_bought') or 0.00,
        }

        # --- 5. CONSTRUIR EL CONTEXTO FINAL ---
        context = {
            'page_title': 'Reporte por Cliente',
            'transactions': transactions_qs.order_by('-created_at'),
            'clients': all_clients,  # Aseguramos pasar la lista completa de clientes
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
        context['page_title'] = f"Nueva Operación para {client.name}"
        context['cancel_url'] = reverse_lazy('client-detail', kwargs={'pk': client.pk})
        return context

    def form_valid(self, form):
        """
        Procesa el formulario cuando es válido.
        """
        # 1. No guardar en la base de datos todavía (commit=False).
        #    Esto nos devuelve una instancia del modelo sin guardar.
        self.object = form.save(commit=False)
        
        # 2. Asignar los datos que no vienen del formulario.
        self.object.client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        self.object.operator = self.request.user
        
        # 3. Ahora guardamos el objeto completo en la base de datos.
        #    En este punto se ejecuta el método save() de nuestro modelo.
        self.object.save()
        
        # Llamamos a super() para que se encargue de la redirección.
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
