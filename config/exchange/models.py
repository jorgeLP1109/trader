# exchange/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver

# --- Modelo de Usuario Personalizado ---
class User(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Administrador'),
        ('operator', 'Operador'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='operator')

# --- Modelo de Cliente ---
class Client(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nombre Completo")
    identifier = models.CharField(max_length=20, unique=True, verbose_name="Cédula o RIF")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono")
    email = models.EmailField(blank=True, null=True, verbose_name="Correo Electrónico")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_balance(self):
        """
        Calcula el balance pendiente de un cliente específico,
        usando la nueva estructura del modelo Transaction.
        """
        # --- Lo que el cliente NOS DEBE ---
        # Nos debe BOLÍVARES (porque les vendimos USD)
        debe_bs = self.transactions.filter(
            status='pending_payment',
            operation_type='sell_usd'
        ).aggregate(total=Sum('amount_bs'))['total'] or 0.00
        
        # Nos debe DÓLARES (porque les compramos USD)
        debe_usd = self.transactions.filter(
            status='pending_payment',
            operation_type='buy_usd'
        ).aggregate(total=Sum('amount_usd'))['total'] or 0.00

        # --- Lo que nosotros LE DEBEMOS al cliente ---
        # Le debemos BOLÍVARES (porque nos dieron USD)
        le_debemos_bs = self.transactions.filter(
            status='pending_delivery',
            operation_type='buy_usd'
        ).aggregate(total=Sum('amount_bs'))['total'] or 0.00

        # Le debemos DÓLARES (porque nos pagaron en BS)
        le_debemos_usd = self.transactions.filter(
            status='pending_delivery',
            operation_type='sell_usd'
        ).aggregate(total=Sum('amount_usd'))['total'] or 0.00

        return {
            'debe_usd': debe_usd,
            'debe_bs': debe_bs,
            'le_debemos_usd': le_debemos_usd,
            'le_debemos_bs': le_debemos_bs,
        }

# --- Modelo de Transacción (Versión Actualizada) ---
class Transaction(models.Model):
    OPERATION_CHOICES = (
        ('sell_usd', 'Venta de Dólares (Cliente recibe USD, paga con BS)'),
        ('buy_usd', 'Compra de Dólares (Cliente recibe BS, paga con USD)'),
    )
    STATUS_CHOICES = (
        ('pending_payment', 'Pendiente por Recibir Pago del Cliente'),
        ('pending_delivery', 'Pendiente por Entregar Dinero al Cliente'),
        ('completed', 'Completada'),
        ('cancelled', 'Anulada'),
    )
    
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='transactions', verbose_name="Cliente")
    operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Operador")
    operation_type = models.CharField(max_length=10, choices=OPERATION_CHOICES, verbose_name="Tipo de Operación")
    
    amount_usd = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Monto en Dólares (USD)")
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Tasa de Cambio (BS por $1)")
    amount_bs = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Monto en Bolívares (BS)", blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending_payment', verbose_name="Estado")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas")
    transaction_date = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Transacción")

    def __str__(self):
        return f"Transacción #{self.id} - {self.client.name}"

    def save(self, *args, **kwargs):
        self.amount_bs = self.amount_usd * self.exchange_rate
        super().save(*args, **kwargs)

# --- Modelo de Efectivo Disponible (Singleton) ---
class CashOnHand(models.Model):
    """
    Un modelo Singleton para registrar el efectivo disponible.
    Solo existirá una fila en esta tabla.
    """
    total_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Total en Dólares (USD)")
    total_bs = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Total en Bolívares (BS)")

    def __str__(self):
        return "Efectivo Disponible"

    class Meta:
        verbose_name_plural = "Efectivo Disponible"

    def save(self, *args, **kwargs):
        self.pk = 1
        super(CashOnHand, self).save(*args, **kwargs)


# ==============================================================================
# SEÑALES (SIGNALS) DE DJANGO
# ==============================================================================

@receiver(post_save, sender=Transaction)
def update_cash_on_hand(sender, instance, created, **kwargs):
    cash, _ = CashOnHand.objects.get_or_create(pk=1)
    
    # Buscamos si hay una sesión abierta hoy
    try:
        active_session = DailySession.objects.get(status='open')
    except DailySession.DoesNotExist:
        active_session = None # No hay sesión activa, no hacemos nada

    if instance.status == 'completed' and (created or 'status' in (kwargs.get('update_fields') or [])):
        
        # Actualizamos la caja y la sesión activa
        if instance.operation_type == 'sell_usd':
            # Venta de Dólares: BAJA USD, SUBE BS
            if active_session:
                active_session.total_usd_out += instance.amount_usd
                active_session.total_bs_in += instance.amount_bs
            cash.total_usd -= instance.amount_usd
            cash.total_bs += instance.amount_bs
            
        elif instance.operation_type == 'buy_usd':
            # Compra de Dólares: SUBE USD, BAJA BS
            if active_session:
                active_session.total_usd_in += instance.amount_usd
                active_session.total_bs_out += instance.amount_bs
            cash.total_usd += instance.amount_usd
            cash.total_bs -= instance.amount_bs
            
        cash.save()
        if active_session:
            active_session.save()



class DailySession(models.Model):
    """
    Registra la apertura, cierre y resumen de cada jornada de trabajo.
    """
    STATUS_CHOICES = (
        ('open', 'Abierta'),
        ('closed', 'Cerrada'),
    )
    
    date = models.DateField(unique=True, verbose_name="Fecha de la Jornada")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='closed', verbose_name="Estado")
    
    # Saldos al INICIO del día
    opening_balance_usd = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Saldo Inicial USD")
    opening_balance_bs = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Saldo Inicial BS")
    
    # Saldos al FINAL del día (calculados al cerrar)
    closing_balance_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Saldo Final USD")
    closing_balance_bs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Saldo Final BS")
    
    # Resumen de operaciones del día (calculados al cerrar)
    total_usd_in = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Total USD Recibidos")
    total_usd_out = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Total USD Entregados")
    total_bs_in = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Total BS Recibidos")
    total_bs_out = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Total BS Entregados")

    opened_by = models.ForeignKey(User, related_name='sessions_opened', on_delete=models.SET_NULL, null=True, blank=True)
    closed_by = models.ForeignKey(User, related_name='sessions_closed', on_delete=models.SET_NULL, null=True, blank=True)
    
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Jornada del {self.date.strftime('%d/%m/%Y')} - {self.get_status_display()}"

    class Meta:
        ordering = ['-date']        