#!/usr/bin/env python3
"""
Script para actualizar las ganancias de las transacciones existentes 
usando los nuevos campos de equivalencias mejorados.
"""

import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from exchange.models import AdvancedTransaction
from decimal import Decimal

def update_existing_profit_equivalencies():
    """
    Actualiza las ganancias existentes para usar los nuevos campos mejorados
    """
    print("Iniciando actualización de equivalencias de ganancias...")
    
    # Obtener todas las transacciones completadas
    transactions = AdvancedTransaction.objects.filter(status='completed')
    total_count = transactions.count()
    
    print(f"Encontradas {total_count} transacciones completadas para procesar.")
    
    updated_count = 0
    
    for tx in transactions:
        try:
            # Determinar la moneda de la ganancia basada en el tipo de operación
            if tx.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']:
                # Ganancias por spread - están en BS
                tx.profit_bs_equivalent = tx.profit if tx.profit else Decimal('0.00')
                # Convertir a USD usando la tasa de la operación o una tasa promedio
                if tx.rate_or_fee and tx.rate_or_fee > 0:
                    tx.profit_usd_equivalent = tx.profit_bs_equivalent / tx.rate_or_fee
                else:
                    tx.profit_usd_equivalent = tx.profit_bs_equivalent / Decimal('36.0')
                    
            elif tx.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
                # Ganancias por comisión - están en USD/USDT
                tx.profit_usd_equivalent = tx.profit if tx.profit else Decimal('0.00')
                # Convertir a BS usando una tasa promedio
                tx.profit_bs_equivalent = tx.profit_usd_equivalent * Decimal('36.0')
            else:
                # Sin ganancia
                tx.profit_usd_equivalent = Decimal('0.00')
                tx.profit_bs_equivalent = Decimal('0.00')
            
            # Guardar los cambios
            tx.save(update_fields=['profit_usd_equivalent', 'profit_bs_equivalent'])
            updated_count += 1
            
            if updated_count % 50 == 0:
                print(f"Procesadas {updated_count}/{total_count} transacciones...")
                
        except Exception as e:
            print(f"Error procesando transacción {tx.id}: {e}")
            continue
    
    print(f"✅ Actualización completada: {updated_count}/{total_count} transacciones actualizadas.")

if __name__ == "__main__":
    try:
        update_existing_profit_equivalencies()
    except KeyboardInterrupt:
        print("\n❌ Actualización cancelada por el usuario.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error durante la actualización: {e}")
        sys.exit(1)
