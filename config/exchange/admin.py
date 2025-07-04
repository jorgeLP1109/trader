# exchange/admin.py

from django.contrib import admin, messages
from .models import User, Client, AdvancedTransaction, CashVault, VaultSession

# ==============================================================================
# ACCIONES DE ADMINISTRACIÓN PERSONALIZADAS
# ==============================================================================

@admin.action(description='Resetear TODOS los datos transaccionales (Clientes, Operaciones, Sesiones)')
def reset_transactional_data(modeladmin, request, queryset):
    """
    Esta acción borra TODOS los clientes, operaciones y sesiones,
    y resetea los saldos de las cajas.
    """
    try:
        AdvancedTransaction.objects.all().delete()
        VaultSession.objects.all().delete()
        Client.objects.all().delete()
        
        CashVault.objects.all().update(
            balance_usd=0, balance_bs=0, balance_usdt=0, balance_zelle=0
        )
        
        modeladmin.message_user(request, "Todos los datos transaccionales han sido eliminados y las cajas reseteadas.", messages.SUCCESS)

    except Exception as e:
        modeladmin.message_user(request, f"Ocurrió un error durante el reseteo: {e}", messages.ERROR)


# ==============================================================================
# CONFIGURACIONES DE MODELOS EN EL ADMIN
# ==============================================================================

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'identifier', 'phone', 'email')
    search_fields = ('name', 'identifier')
    actions = [reset_transactional_data]


@admin.register(AdvancedTransaction)
class AdvancedTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'operation_type', 'amount_in', 'rate_or_fee', 'amount_out', 'profit', 'status', 'created_at')
    list_filter = ('status', 'operation_type', 'client')
    search_fields = ('client__name', 'id')
    readonly_fields = ('amount_out', 'profit') # Se calculan solos


@admin.register(VaultSession)
class VaultSessionAdmin(admin.ModelAdmin):
    list_display = ('vault', 'date', 'status', 'opened_by', 'closed_by')
    list_filter = ('vault', 'status', 'date')


# ==============================================================================
# REGISTRO DE MODELOS RESTANTES
# ==============================================================================

# El modelo User ya es manejado por Django, pero si tienes un modelo personalizado
# y no lo has registrado de otra forma, esta es la manera.
# Si el error persiste, es porque ya está registrado en otro lado.
# En ese caso, comenta o elimina la siguiente línea.
try:
    admin.site.register(User)
except admin.sites.AlreadyRegistered:
    pass

admin.site.register(CashVault)