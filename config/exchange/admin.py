from django.contrib import admin
from .models import User, Client, Transaction
from .models import User, Client, Transaction, CashOnHand 

# Personalizar la vista de admin para que sea más útil
class TransactionAdmin(admin.ModelAdmin):
    # Usamos los nuevos nombres de los campos: amount_usd y amount_bs
    list_display = (
        'id', 
        'client', 
        'operation_type', 
        'amount_usd',  # <-- CAMBIO AQUÍ
        'exchange_rate', 
        'amount_bs',   # <-- CAMBIO AQUÍ
        'status', 
        'transaction_date'
    )
    list_filter = ('status', 'operation_type', 'client', 'transaction_date')
    search_fields = ('client__name', 'id')
    readonly_fields = ('amount_bs',) # Hacemos que el monto en BS sea de solo lectura, ya que se calcula solo.

class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'identifier', 'phone', 'email')
    search_fields = ('name', 'identifier')

admin.site.register(User)
admin.site.register(Client, ClientAdmin)
admin.site.register(Transaction, TransactionAdmin)

admin.site.register(CashOnHand)