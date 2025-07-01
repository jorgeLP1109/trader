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
from .models import Client, Transaction, User, CashOnHand, DailySession
from django.contrib.auth import authenticate
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from .decorators import admin_required
from django.utils import timezone
from datetime import date







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

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'exchange/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Dashboard Principal'

        # --- CÁLCULOS DE TOTALES ---
        context['total_receivable_bs'] = Transaction.objects.filter(status='pending_payment', operation_type='sell_usd').aggregate(total=Sum('amount_bs'))['total'] or 0.00
        context['total_receivable_usd'] = Transaction.objects.filter(status='pending_payment', operation_type='buy_usd').aggregate(total=Sum('amount_usd'))['total'] or 0.00
        context['total_payable_bs'] = Transaction.objects.filter(status='pending_delivery', operation_type='buy_usd').aggregate(total=Sum('amount_bs'))['total'] or 0.00
        context['total_payable_usd'] = Transaction.objects.filter(status='pending_delivery', operation_type='sell_usd').aggregate(total=Sum('amount_usd'))['total'] or 0.00

        # --- LISTAS DE CLIENTES ---
        context['clients_who_owe'] = Client.objects.filter(transactions__status='pending_payment').distinct()
        context['clients_we_owe'] = Client.objects.filter(transactions__status='pending_delivery').distinct()

        # --- CAJA ---
        cash, created = CashOnHand.objects.get_or_create(pk=1)
        context['cash_on_hand_usd'] = cash.total_usd
        context['cash_on_hand_bs'] = cash.total_bs

        return context


# ==============================================================================
# VISTAS PARA CLIENTES (CRUD)
# ==============================================================================

class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = 'exchange/client_list.html'
    context_object_name = 'clients'
    paginate_by = 10

class ClientDetailView(LoginRequiredMixin, DetailView):
    model = Client
    template_name = 'exchange/client_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Aquí actualizaremos get_balance() más adelante. Por ahora, lo dejamos así.
        context['balance'] = self.get_object().get_balance()
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

class TransactionCreateView(LoginRequiredMixin, CreateView):
    model = Transaction
    template_name = 'exchange/transaction_form.html'
    fields = ['operation_type', 'amount_usd', 'exchange_rate', 'status', 'notes']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        context['page_title'] = f'Nueva Transacción para {client.name}'
        context['cancel_url'] = reverse_lazy('client-detail', kwargs={'pk': client.pk})
        return context

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['amount_usd'].widget.attrs.update({'id': 'id_amount_usd', 'onkeyup': 'calculateTotal()', 'autocomplete': 'off'})
        form.fields['exchange_rate'].widget.attrs.update({'id': 'id_exchange_rate', 'onkeyup': 'calculateTotal()', 'autocomplete': 'off'})
        form.fields['notes'].widget = forms.Textarea(attrs={'rows': 3})
        return form

    def form_valid(self, form):
        form.instance.client = get_object_or_404(Client, pk=self.kwargs['client_pk'])
        form.instance.operator = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
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
# VISTAS DE API PARA GRÁFICOS
# ==============================================================================

def exchange_volume_chart_data(request):
    """
    API que devuelve el número de transacciones completadas por mes.
    """
    data = Transaction.objects.filter(status='completed') \
        .annotate(month=TruncMonth('transaction_date')) \
        .values('month') \
        .annotate(count=Count('id')) \
        .order_by('month')
    
    labels = [d['month'].strftime('%B %Y') for d in data]
    values = [d['count'] for d in data]
    
    return JsonResponse({'labels': labels, 'data': values})


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
