#!/usr/bin/env python
"""
Script para migrar las ganancias existentes al nuevo sistema mejorado.
Este script debe ejecutarse desde el directorio raíz de Django después de aplicar las migraciones.

Uso: python migrate_profit_fields.py
"""

import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from exchange.models import AdvancedTransaction
from decimal import Decimal

def migrate_profit_fields():
    """Migra todas las transacciones existentes al nuevo sistema de ganancias."""
    
    # Obtener todas las transacciones que no han sido migradas
    transactions = AdvancedTransaction.objects.filter(
        profit_amount=0,  # Solo las que no han sido calculadas con el nuevo sistema
        status='completed'
    )
    
    updated_count = 0
    
    print(f"Encontradas {transactions.count()} transacciones para migrar...")
    
    for transaction in transactions:
        try:
            # El método save() automáticamente calculará los nuevos campos
            # usando el método calculate_improved_profit()
            transaction.save()
            updated_count += 1
            
            if updated_count % 50 == 0:
                print(f"Migradas {updated_count} transacciones...")
                
        except Exception as e:
            print(f"Error migrando transacción #{transaction.id}: {str(e)}")
    
    print(f"\n✅ Migración completada: {updated_count} transacciones actualizadas.")
    
    # Mostrar estadísticas
    total_transactions = AdvancedTransaction.objects.count()
    migrated_transactions = AdvancedTransaction.objects.exclude(profit_amount=0).count()
    
    print(f"\n📊 Estadísticas:")
    print(f"Total de transacciones: {total_transactions}")
    print(f"Transacciones migradas: {migrated_transactions}")
    print(f"Pendientes por migrar: {total_transactions - migrated_transactions}")
    
    # Mostrar resumen de ganancias
    if migrated_transactions > 0:
        from django.db.models import Sum
        
        total_usd = AdvancedTransaction.objects.aggregate(
            total=Sum('profit_usd_equivalent')
        )['total'] or Decimal('0')
        
        total_bs = AdvancedTransaction.objects.aggregate(
            total=Sum('profit_bs_equivalent')
        )['total'] or Decimal('0')
        
        print(f"\n💰 Ganancias totales calculadas:")
        print(f"USD: ${total_usd:,.2f}")
        print(f"BS: {total_bs:,.2f}")

if __name__ == "__main__":
    print("🔄 Iniciando migración de campos de ganancia...")
    migrate_profit_fields()
    print("✨ ¡Migración completada exitosamente!")
