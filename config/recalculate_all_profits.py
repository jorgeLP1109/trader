#!/usr/bin/env python
"""
Script para recalcular todas las ganancias de las transacciones existentes
usando el sistema mejorado de campos de ganancia.

Ejecutar desde el directorio del proyecto con:
python recalculate_all_profits.py
"""

import os
import sys
import django
from decimal import Decimal

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import models
from exchange.models import AdvancedTransaction

def recalculate_all_profits():
    """Recalcula las ganancias para todas las transacciones existentes."""
    
    print("🔄 Iniciando recálculo de ganancias para todas las transacciones...")
    
    # Obtener todas las transacciones
    all_transactions = AdvancedTransaction.objects.all()
    total_count = all_transactions.count()
    
    if total_count == 0:
        print("❌ No se encontraron transacciones en la base de datos.")
        return
    
    print(f"📊 Encontradas {total_count} transacciones para procesar...")
    
    # Contadores
    updated_count = 0
    error_count = 0
    total_profit_usd = Decimal('0.00')
    total_profit_bs = Decimal('0.00')
    
    # Procesar cada transacción
    for i, transaction in enumerate(all_transactions, 1):
        try:
            # Guardar valores originales para comparación
            original_profit_usd = transaction.profit_usd_equivalent
            original_profit_bs = transaction.profit_bs_equivalent
            
            # El método save() del modelo recalculará automáticamente las ganancias
            transaction.save()
            
            # Verificar si hubo cambios
            if (transaction.profit_usd_equivalent != original_profit_usd or 
                transaction.profit_bs_equivalent != original_profit_bs):
                updated_count += 1
            
            # Acumular totales
            total_profit_usd += transaction.profit_usd_equivalent or Decimal('0.00')
            total_profit_bs += transaction.profit_bs_equivalent or Decimal('0.00')
            
            # Mostrar progreso cada 10 transacciones
            if i % 10 == 0 or i == total_count:
                print(f"📈 Progreso: {i}/{total_count} transacciones procesadas...")
                
        except Exception as e:
            error_count += 1
            print(f"❌ Error procesando transacción #{transaction.id}: {e}")
            continue
    
    # Mostrar resumen final
    print(f"\n{'='*60}")
    print(f"✅ RECÁLCULO COMPLETADO")
    print(f"{'='*60}")
    print(f"📊 Total de transacciones: {total_count}")
    print(f"🔄 Transacciones actualizadas: {updated_count}")
    print(f"❌ Errores encontrados: {error_count}")
    print(f"💰 Ganancia total USD: ${total_profit_usd:,.2f}")
    print(f"💰 Ganancia total BS: {total_profit_bs:,.2f}")
    
    # Mostrar algunas transacciones de ejemplo
    print(f"\n📋 MUESTRA DE TRANSACCIONES CON GANANCIAS:")
    print(f"{'='*60}")
    sample_transactions = AdvancedTransaction.objects.filter(
        profit_usd_equivalent__gt=0
    ).order_by('-created_at')[:5]
    
    if sample_transactions.exists():
        for tx in sample_transactions:
            print(f"#{tx.id} - {tx.client.name} - {tx.get_operation_type_display()}")
            print(f"  🔸 Ganancia: {tx.get_profit_display()}")
            print(f"  🔸 Fecha: {tx.created_at.strftime('%d/%m/%Y %H:%M')}")
            print()
    else:
        print("❌ No se encontraron transacciones con ganancias calculadas.")
        print("⚠️  Esto podría indicar un problema con el cálculo de ganancias.")

def show_transactions_summary():
    """Muestra un resumen de las transacciones por tipo y estado."""
    
    print(f"\n📊 RESUMEN POR TIPO Y ESTADO:")
    print(f"{'='*60}")
    
    # Resumen por estado
    for status_code, status_name in AdvancedTransaction.STATUS_CHOICES:
        count = AdvancedTransaction.objects.filter(status=status_code).count()
        print(f"🔸 {status_name}: {count} transacciones")
    
    print()
    
    # Resumen por tipo de operación
    for op_code, op_name in AdvancedTransaction.OPERATION_CHOICES:
        count = AdvancedTransaction.objects.filter(operation_type=op_code).count()
        avg_profit = AdvancedTransaction.objects.filter(
            operation_type=op_code
        ).aggregate(
            avg=models.Avg('profit_usd_equivalent')
        )['avg'] or Decimal('0.00')
        
        if count > 0:
            print(f"🔸 {op_name}: {count} ops, promedio ${avg_profit:.2f} USD")

if __name__ == '__main__':
    try:
        show_transactions_summary()
        recalculate_all_profits()
        print(f"\n🎉 ¡Proceso completado exitosamente!")
        
    except KeyboardInterrupt:
        print(f"\n⚠️  Proceso interrumpido por el usuario.")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        sys.exit(1)
