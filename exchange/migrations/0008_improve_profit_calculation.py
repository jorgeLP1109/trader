# Generated migration for improved profit calculation

from django.db import migrations, models
from decimal import Decimal

def migrate_existing_profits(apps, schema_editor):
    """
    Migra las ganancias existentes al nuevo formato.
    """
    AdvancedTransaction = apps.get_model('exchange', 'AdvancedTransaction')
    
    for transaction in AdvancedTransaction.objects.all():
        # Determinar moneda de ganancia basada en tipo de operación
        if transaction.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
            transaction.profit_currency = 'USD'
            transaction.profit_amount = transaction.profit or Decimal('0.00')
            transaction.profit_usd_equivalent = transaction.profit_amount
            # Convertir a BS usando tasa aproximada
            transaction.profit_bs_equivalent = transaction.profit_amount * Decimal('40.0')
        else:
            transaction.profit_currency = 'BS'
            transaction.profit_amount = transaction.profit or Decimal('0.00')
            transaction.profit_bs_equivalent = transaction.profit_amount
            # Convertir a USD
            if transaction.profit_amount > 0:
                transaction.profit_usd_equivalent = transaction.profit_amount / Decimal('40.0')
            else:
                transaction.profit_usd_equivalent = Decimal('0.00')
        
        # Establecer tasa USD/BS usada
        if transaction.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS']:
            transaction.usd_bs_rate_used = transaction.rate_or_fee
        else:
            transaction.usd_bs_rate_used = Decimal('40.0')
            
        transaction.save()

def reverse_migrate_profits(apps, schema_editor):
    """
    Reversa la migración manteniendo solo el campo profit original.
    """
    pass  # Los campos se eliminan automáticamente

class Migration(migrations.Migration):

    dependencies = [
        ('exchange', '0007_advancedtransaction_base_rate_and_more'),
    ]

    operations = [
        # Agregar nuevos campos de ganancia
        migrations.AddField(
            model_name='advancedtransaction',
            name='profit_amount',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=12, verbose_name='Ganancia (Monto)'),
        ),
        migrations.AddField(
            model_name='advancedtransaction',
            name='profit_currency',
            field=models.CharField(default='USD', max_length=5, verbose_name='Moneda de Ganancia'),
        ),
        migrations.AddField(
            model_name='advancedtransaction',
            name='profit_usd_equivalent',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=12, verbose_name='Ganancia en USD'),
        ),
        migrations.AddField(
            model_name='advancedtransaction',
            name='profit_bs_equivalent',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=12, verbose_name='Ganancia en BS'),
        ),
        migrations.AddField(
            model_name='advancedtransaction',
            name='usd_bs_rate_used',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True, verbose_name='Tasa USD/BS utilizada'),
        ),
        
        # Migrar datos existentes
        migrations.RunPython(migrate_existing_profits, reverse_migrate_profits),
    ]
