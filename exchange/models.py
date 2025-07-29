# exchange/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal

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
        Calcula el balance pendiente de un cliente, basándose en las
        transacciones pendientes del nuevo modelo AdvancedTransaction.
        """
        # Obtenemos todas las transacciones pendientes de este cliente
        pending_transactions = self.adv_transactions.filter(status='pending')
        
        # --- Lo que el cliente NOS DEBE ---
        # Nos debe BOLÍVARES (cuando le vendemos USD o USDT)
        debe_bs = pending_transactions.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(total=Sum('amount_out'))['total'] or 0.00
        
        # Nos debe DÓLARES (cuando le compramos USD/USDT/Zelle)
        debe_usd = pending_transactions.filter(
            operation_type__in=['BUY_USD_FOR_BS', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
        ).aggregate(total=Sum('amount_in'))['total'] or 0.00


        # --- Lo que nosotros LE DEBEMOS al cliente ---
        # Le debemos BOLÍVARES (cuando nos compra USD/USDT)
        le_debemos_bs = pending_transactions.filter(
            operation_type='BUY_USD_FOR_BS'
        ).aggregate(total=Sum('amount_out'))['total'] or 0.00
        
        # Le debemos DÓLARES/USDT/ZELLE
        debe_entregar_usd = pending_transactions.filter(
            operation_type='SELL_USD_FOR_BS'
        ).aggregate(total=Sum('amount_in'))['total'] or 0.00
        
        debe_entregar_usdt = pending_transactions.filter(
            operation_type__in=['USDT_FOR_BS', 'CASH_FOR_USDT']
        ).aggregate(total=Sum('amount_in'))['total'] or 0.00

        debe_entregar_zelle = pending_transactions.filter(
            operation_type='ZELLE_FOR_CASH'
        ).aggregate(total=Sum('amount_in'))['total'] or 0.00

        # Combinamos todo en un diccionario claro para la plantilla
        return {
            'debe_bs': debe_bs,
            'debe_usd': debe_usd,
            'le_debemos_bs': le_debemos_bs,
            'le_debemos_usd': debe_entregar_usd,
            'le_debemos_usdt': debe_entregar_usdt,
            'le_debemos_zelle': debe_entregar_zelle
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


# --- NUEVOS MODELOS DE CAJA Y SESIONES ---

class CashVault(models.Model):
    """Modelo genérico para una bóveda de dinero (caja)."""
    name = models.CharField(max_length=100, unique=True)
    # Saldos actuales de la caja
    balance_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Saldo USD (Efectivo)")
    balance_bs = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Saldo Bolívares")
    balance_usdt = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Saldo USDT")
    balance_zelle = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Saldo Zelle")

    def __str__(self):
        return self.name

class VaultSession(models.Model):
    """Registra la apertura y cierre de una bóveda de caja específica."""
    vault = models.ForeignKey(CashVault, on_delete=models.CASCADE, related_name='sessions')
    date = models.DateField(verbose_name="Fecha de la Jornada")
    status = models.CharField(max_length=10, choices=[('open', 'Abierta'), ('closed', 'Cerrada')], default='closed')
    
    opening_balance_usd = models.DecimalField(max_digits=12, decimal_places=2)
    opening_balance_bs = models.DecimalField(max_digits=12, decimal_places=2)
    opening_balance_usdt = models.DecimalField(max_digits=12, decimal_places=2)
    opening_balance_zelle = models.DecimalField(max_digits=12, decimal_places=2)
    
    closing_balance_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_balance_bs = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_balance_usdt = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_balance_zelle = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # ... (totalizadores de IN/OUT se quedan igual si los tienes) ...
    
    opened_by = models.ForeignKey(User, related_name='sessions_opened_vault', on_delete=models.SET_NULL, null=True)
    # --- CAMPO AÑADIDO / CORREGIDO ---
    closed_by = models.ForeignKey(User, related_name='sessions_closed_vault', on_delete=models.SET_NULL, null=True, blank=True)
    
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('vault', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"Sesión de {self.vault.name} - {self.date.strftime('%d/%m/%Y')}"


# --- MODELO DE TRANSACCIÓN REFACTORIZADO ---

class ClientWorkSheet(models.Model):
    """
    Representa una hoja de trabajo o un lote de operaciones para un cliente
    en una fecha específica.
    """
    STATUS_CHOICES = (
        ('open', 'Abierta'),
        ('closed', 'Cerrada'),
    )
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='worksheets')
    date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Hoja de trabajo para {self.client.name} - {self.date.strftime('%d/%m/%Y')}"

    class Meta:
        unique_together = ('client', 'date') # Solo una hoja de trabajo por cliente por día          

class AdvancedTransaction(models.Model):
    OPERATION_CHOICES = [
        ('SELL_USD_FOR_BS', 'Venta USD por BS'),
        ('BUY_USD_FOR_BS', 'Compra USD por BS'),
        ('USDT_FOR_CASH', 'Doy USDT, Recibo Efectivo (Comisión %)'),
        ('CASH_FOR_USDT', 'Doy Efectivo, Recibo USDT (Comisión %)'),
        ('USDT_FOR_BS', 'Doy USDT por Bolívares (Tasa)'),
        ('ZELLE_FOR_CASH', 'Doy Zelle, Recibo Efectivo'),
    ]
    STATUS_CHOICES = (('pending', 'Pendiente'), ('completed', 'Completada'), ('cancelled', 'Anulada'),)

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='adv_transactions')
    operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    worksheet = models.ForeignKey(ClientWorkSheet, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    operation_type = models.CharField(max_length=20, choices=OPERATION_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    
    amount_in = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Monto de Entrada")
    rate_or_fee = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Tasa de Operación / Fee (%)")
    
    amount_out = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Monto de Salida (Calculado)")
    profit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=0.00, verbose_name="Ganancia Directa (Comisión)")

    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Aseguramos que los valores sean del tipo Decimal para precisión
        self.rate_or_fee = Decimal(self.rate_or_fee) if self.rate_or_fee is not None else Decimal('0')
        self.amount_in = Decimal(self.amount_in) if self.amount_in is not None else Decimal('0')
        
        # --- LÓGICA DE CÁLCULO CORREGIDA SEGÚN NUEVO MODELO DE NEGOCIO ---
        self.profit = Decimal('0.00')

        # === OPERACIONES CON COMISIÓN/PRIMA ===
        if self.operation_type == 'USDT_FOR_CASH':
            # Doy USDT, recibo Efectivo + Comisión.
            # amount_in = USDT que entrego.
            # rate_or_fee = % de comisión que cobro.
            self.profit = self.amount_in * (self.rate_or_fee / Decimal('100'))
            self.amount_out = self.amount_in + self.profit # Recibo el equivalente en efectivo MÁS mi ganancia.
        
        elif self.operation_type == 'CASH_FOR_USDT':
            # Doy Efectivo, recibo USDT + Comisión.
            # amount_in = Efectivo que entrego.
            # rate_or_fee = % de comisión que cobro.
            self.profit = self.amount_in * (self.rate_or_fee / Decimal('100'))
            self.amount_out = self.amount_in + self.profit # Recibo el equivalente en USDT MÁS mi ganancia.
            
        elif self.operation_type == 'ZELLE_FOR_CASH':
            # Doy Zelle, recibo Efectivo + Comisión.
            # amount_in = Zelle que entrego.
            # rate_or_fee = % de comisión que cobro.
            self.profit = self.amount_in * (self.rate_or_fee / Decimal('100'))
            self.amount_out = self.amount_in + self.profit # Recibo el equivalente en efectivo MÁS mi ganancia.

        # === OPERACIONES CON TASA DE CAMBIO ===
        elif self.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']:
            # La lógica aquí ya es correcta: Monto de Salida = Monto de Entrada * Tasa
            self.amount_out = self.amount_in * self.rate_or_fee
            # La ganancia por spread se calcula en los reportes, no aquí.
            self.profit = Decimal('0.00')

        super().save(*args, **kwargs)



@receiver(post_save, sender=AdvancedTransaction)
def update_vaults_on_transaction_complete(sender, instance, created, **kwargs):
    """
    Actualiza los saldos de las bóvedas correspondientes cuando una
    transacción avanzada se marca como 'completada'.
    """
    # Solo actuar si el estado es 'completada' y es una actualización a este estado
    if instance.status != 'completed' or (not created and 'status' not in (kwargs.get('update_fields') or [])):
        return

    # Mapeo de operación a bóvedas y monedas afectadas
    # Formato: { 'operación': {'bóveda_nombre': {'moneda_a_bajar': 'monto', 'moneda_a_subir': 'monto'}, ...} }
    vault_map = {
        'USDT_FOR_CASH': {'Caja USDT/Efectivo': {'balance_usdt': -instance.amount_in, 'balance_usd': instance.amount_in}},
        'CASH_FOR_USDT': {'Caja USDT/Efectivo': {'balance_usd': -instance.amount_in, 'balance_usdt': instance.amount_in}},
        'USDT_FOR_BS': {'Caja Principal (USD/BS)': {'balance_usdt': -instance.amount_in, 'balance_bs': instance.amount_out}},
        'SELL_USD_FOR_BS': {'Caja Principal (USD/BS)': {'balance_usd': -instance.amount_in, 'balance_bs': instance.amount_out}},
    }
# --- MODELO DE HOJA DE TRABAJO DEL CLIENTE ---
# (Ya definido arriba, eliminar duplicado)

class VaultAdjustment(models.Model):
    """
    Registra un ajuste manual de saldo en una bóveda (caja).
    Sirve como una pista de auditoría para inyecciones o correcciones.
    """
    ADJUSTMENT_TYPE_CHOICES = (
        ('injection', 'Inyección de Capital'),
        ('withdrawal', 'Retiro de Capital'),
        ('correction', 'Corrección de Saldo'),
    )

    vault = models.ForeignKey(CashVault, on_delete=models.PROTECT, related_name='adjustments')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Realizado por")
    adjustment_type = models.CharField(max_length=20, choices=ADJUSTMENT_TYPE_CHOICES, verbose_name="Tipo de Ajuste")
    
    # Cantidad que se suma o resta
    amount_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    amount_bs = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    amount_usdt = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    amount_zelle = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    reason = models.TextField(verbose_name="Motivo del Ajuste")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ajuste en {self.vault.name} el {self.created_at.strftime('%d/%m/%Y')}"