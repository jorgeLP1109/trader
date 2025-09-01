# exchange/models_improved.py
# Versión mejorada del modelo AdvancedTransaction con cálculo de ganancias estandarizado

from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver

class AdvancedTransactionImproved(models.Model):
    """
    Versión mejorada del modelo de transacciones con cálculo de ganancias estandarizado.
    
    PRINCIPIOS DE GANANCIAS:
    1. Todas las ganancias se expresan en la moneda de salida de la operación
    2. Se calcula automáticamente basado en márgenes estándar si no se especifica base_rate
    3. Consistencia en el cálculo entre todos los tipos de operación
    """
    
    OPERATION_CHOICES = [
        ('SELL_USD_FOR_BS', 'Venta USD por BS'),
        ('BUY_USD_FOR_BS', 'Compra USD por BS'), 
        ('USDT_FOR_CASH', 'Cambio USDT → USD (Comisión)'),
        ('CASH_FOR_USDT', 'Cambio USD → USDT (Comisión)'),
        ('USDT_FOR_BS', 'Cambio USDT → BS (Tasa)'),
        ('ZELLE_FOR_CASH', 'Cambio Zelle → USD (Comisión)'),
    ]
    
    STATUS_CHOICES = (
        ('pending', 'Pendiente'),
        ('completed', 'Completada'),
        ('cancelled', 'Anulada'),
    )

    client = models.ForeignKey('Client', on_delete=models.CASCADE, related_name='adv_transactions')
    operator = models.ForeignKey('User', on_delete=models.SET_NULL, null=True)
    worksheet = models.ForeignKey('ClientWorkSheet', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    operation_type = models.CharField(max_length=20, choices=OPERATION_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    
    # Campos de la operación
    amount_in = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Monto de Entrada")
    rate_or_fee = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Tasa de Operación / Fee (%)")
    
    # Campo opcional para especificar costo/tasa base
    base_rate = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True,
        verbose_name="Tasa Base/Costo (Opcional)",
        help_text="Tu costo de referencia. Si no se especifica, usa márgenes estándar."
    )
    
    # Campos calculados automáticamente
    amount_out = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Campos de ganancia mejorados
    profit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Ganancia (Monto)")
    profit_currency = models.CharField(max_length=5, default='USD', verbose_name="Moneda de Ganancia")
    profit_usd_equivalent = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Ganancia en USD")
    profit_bs_equivalent = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Ganancia en BS")
    
    # Campos de contexto para conversión
    usd_bs_rate_used = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True, 
                                          verbose_name="Tasa USD/BS utilizada")
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """
        Cálculo estandarizado de ganancias con conversión automática entre monedas.
        """
        # Convertir a Decimal para cálculos precisos
        self.rate_or_fee = Decimal(self.rate_or_fee or '0')
        self.amount_in = Decimal(self.amount_in or '0')
        if self.base_rate is not None:
            self.base_rate = Decimal(self.base_rate)
        
        # --- 1. CALCULAR MONTO DE SALIDA ---
        self._calculate_amount_out()
        
        # --- 2. CALCULAR GANANCIAS ---
        self._calculate_profit()
        
        # --- 3. CONVERTIR GANANCIAS A DIFERENTES MONEDAS ---
        self._convert_profit_currencies()
        
        super().save(*args, **kwargs)

    def _calculate_amount_out(self):
        """Calcula el monto de salida según el tipo de operación."""
        if self.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']:
            # Operaciones de tasa: salida = entrada * tasa
            self.amount_out = self.amount_in * self.rate_or_fee
        elif self.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
            # Operaciones de comisión: salida = entrada + comisión
            commission = self.amount_in * (self.rate_or_fee / Decimal('100'))
            self.amount_out = self.amount_in + commission

    def _calculate_profit(self):
        """
        Calcula la ganancia según el tipo de operación con lógica estandarizada.
        """
        self.profit_amount = Decimal('0.00')
        
        if self.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
            # OPERACIONES DE COMISIÓN
            self.profit_amount = self.amount_in * (self.rate_or_fee / Decimal('100'))
            self.profit_currency = 'USD'  # Comisiones siempre en USD
            
        elif self.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']:
            # OPERACIONES DE SPREAD
            self.profit_currency = 'BS'  # Spread siempre en BS
            
            if self.base_rate:
                # Usar tasa base especificada
                if self.operation_type in ['SELL_USD_FOR_BS', 'USDT_FOR_BS']:
                    # Vendemos: ganancia = (tasa_cliente - tasa_costo) * monto
                    self.profit_amount = (self.rate_or_fee - self.base_rate) * self.amount_in
                elif self.operation_type == 'BUY_USD_FOR_BS':
                    # Compramos: ganancia = (tasa_costo - tasa_cliente) * monto
                    self.profit_amount = (self.base_rate - self.rate_or_fee) * self.amount_in
            else:
                # Usar márgenes estándar automáticos
                self._calculate_automatic_profit()

    def _calculate_automatic_profit(self):
        """
        Calcula ganancia usando márgenes estándar cuando no se especifica base_rate.
        """
        # Márgenes estándar (pueden ajustarse según tu negocio)
        STANDARD_MARGINS = {
            'SELL_USD_FOR_BS': Decimal('0.5'),  # 0.5 Bs de margen por USD vendido
            'BUY_USD_FOR_BS': Decimal('0.5'),   # 0.5 Bs de margen por USD comprado
            'USDT_FOR_BS': Decimal('0.3'),      # 0.3 Bs de margen por USDT
        }
        
        margin = STANDARD_MARGINS.get(self.operation_type, Decimal('0'))
        self.profit_amount = margin * self.amount_in

    def _convert_profit_currencies(self):
        """
        Convierte las ganancias a USD y BS para reportes consolidados.
        """
        if self.profit_currency == 'USD':
            self.profit_usd_equivalent = self.profit_amount
            
            # Convertir a BS usando la tasa de la operación o una tasa de referencia
            conversion_rate = self._get_conversion_rate_to_bs()
            self.profit_bs_equivalent = self.profit_amount * conversion_rate
            
        elif self.profit_currency == 'BS':
            self.profit_bs_equivalent = self.profit_amount
            
            # Convertir a USD
            conversion_rate = self._get_conversion_rate_to_bs()
            if conversion_rate > 0:
                self.profit_usd_equivalent = self.profit_amount / conversion_rate
            else:
                self.profit_usd_equivalent = Decimal('0')

    def _get_conversion_rate_to_bs(self):
        """
        Obtiene la tasa de conversión USD → BS para esta transacción.
        """
        if self.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS']:
            # Usar la tasa de la misma operación
            self.usd_bs_rate_used = self.rate_or_fee
            return self.rate_or_fee
        else:
            # Usar una tasa de referencia (promedio reciente o configurada)
            recent_rate = self._get_recent_usd_bs_rate()
            self.usd_bs_rate_used = recent_rate
            return recent_rate

    def _get_recent_usd_bs_rate(self):
        """
        Obtiene la tasa USD/BS más reciente de operaciones completadas.
        """
        from datetime import timedelta
        
        recent_transaction = AdvancedTransactionImproved.objects.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS'],
            status='completed',
            created_at__gte=timezone.now() - timedelta(days=7)
        ).order_by('-created_at').first()
        
        if recent_transaction:
            return recent_transaction.rate_or_fee
        else:
            # Tasa de fallback si no hay operaciones recientes
            return Decimal('40.0')  # Ajustar según tu contexto

    # Métodos de utilidad para reportes
    def get_profit_display(self):
        """Retorna la ganancia formateada para mostrar."""
        if self.profit_currency == 'USD':
            return f"${self.profit_amount:,.2f}"
        elif self.profit_currency == 'BS':
            return f"{self.profit_amount:,.2f} Bs."
        else:
            return f"{self.profit_amount:,.2f} {self.profit_currency}"

    def get_client_perspective(self):
        """Retorna una descripción clara de lo que hizo el cliente."""
        perspectives = {
            'SELL_USD_FOR_BS': f"Compró ${self.amount_in:,.2f} USD por {self.amount_out:,.2f} Bs.",
            'BUY_USD_FOR_BS': f"Vendió ${self.amount_in:,.2f} USD por {self.amount_out:,.2f} Bs.",
            'USDT_FOR_CASH': f"Cambió {self.amount_in:,.2f} USDT por ${self.amount_out:,.2f} USD",
            'CASH_FOR_USDT': f"Cambió ${self.amount_in:,.2f} USD por {self.amount_out:,.2f} USDT",
            'USDT_FOR_BS': f"Cambió {self.amount_in:,.2f} USDT por {self.amount_out:,.2f} Bs.",
            'ZELLE_FOR_CASH': f"Cambió ${self.amount_in:,.2f} Zelle por ${self.amount_out:,.2f} USD"
        }
        return perspectives.get(self.operation_type, "Operación especial")

    class Meta:
        db_table = 'exchange_advancedtransaction'  # Usar la misma tabla
        ordering = ['-created_at']
        
    def __str__(self):
        return f"Operación #{self.id} - {self.client.name} - {self.get_profit_display()}"
