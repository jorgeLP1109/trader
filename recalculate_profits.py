#!/usr/bin/env python3
"""
Script para recalcular las ganancias de transacciones existentes que tienen profit=0
pero deberían tener ganancia según las reglas de negocio.
"""

import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from exchange.models import AdvancedTransaction
from decimal import Decimal

def recalculate_profits():
    """
    Recalcula las ganancias de transacciones que deberían tener ganancia pero tienen profit=0
    """
    print("Iniciando recálculo de ganancias...")
    
    # Obtener transacciones con profit = 0 que podrían tener ganancia
    transactions = AdvancedTransaction.objects.filter(
        status='completed',
        profit=0
    )
    
    total_count = transactions.count()
    print(f"Encontradas {total_count} transacciones con profit=0 para revisar.")
    
    updated_count = 0
    
    # Definir tasas base aproximadas para el cálculo
    BASE_RATES = {
        'BUY_USD_FOR_BS': Decimal('175.0'),  # Tasa base para compra
        'SELL_USD_FOR_BS': Decimal('180.0'),  # Tasa base para venta
        'USDT_FOR_BS': Decimal('178.0'),  # Tasa base para USDT
    }
    
    BASE_COMMISSION_RATE = Decimal('2.0')  # 2% comisión base
    
    for tx in transactions:
        try:
            original_profit = tx.profit
            
            # Recalcular ganancia según el tipo de operación
            if tx.operation_type == 'SELL_USD_FOR_BS':
                # Ganancia por spread en venta de USD
                base_rate = BASE_RATES['SELL_USD_FOR_BS']
                spread = tx.rate_or_fee - base_rate
                tx.profit = spread * tx.amount_in
                
            elif tx.operation_type == 'BUY_USD_FOR_BS':
                # Ganancia por spread en compra de USD
                base_rate = BASE_RATES['BUY_USD_FOR_BS']
                spread = base_rate - tx.rate_or_fee
                tx.profit = spread * tx.amount_in
                
            elif tx.operation_type == 'USDT_FOR_BS':
                # Ganancia por spread en USDT
                base_rate = BASE_RATES['USDT_FOR_BS']
                spread = tx.rate_or_fee - base_rate
                tx.profit = spread * tx.amount_in
                
            elif tx.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
                # Ganancia por comisión
                if tx.rate_or_fee > 0:
                    commission_rate = tx.rate_or_fee
                else:
                    commission_rate = BASE_COMMISSION_RATE
                tx.profit = tx.amount_in * (commission_rate / Decimal('100'))
                
            # Recalcular equivalencias usando la nueva ganancia
            if tx.operation_type in ['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']:
                # Ganancias por spread - están en BS
                tx.profit_bs_equivalent = tx.profit
                if tx.rate_or_fee and tx.rate_or_fee > 0:
                    tx.profit_usd_equivalent = tx.profit / tx.rate_or_fee
                else:
                    tx.profit_usd_equivalent = tx.profit / Decimal('36.0')
                    
            elif tx.operation_type in ['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']:
                # Ganancias por comisión - están en USD
                tx.profit_usd_equivalent = tx.profit
                tx.profit_bs_equivalent = tx.profit * Decimal('36.0')
            
            # Solo guardar si hubo cambio
            if tx.profit != original_profit:
                tx.save(update_fields=['profit', 'profit_usd_equivalent', 'profit_bs_equivalent'])
                updated_count += 1
                print(f"TX {tx.id}: {tx.operation_type} - Nueva ganancia: {tx.profit} | USD: {tx.profit_usd_equivalent} | BS: {tx.profit_bs_equivalent}")
                
        except Exception as e:
            print(f"Error procesando transacción {tx.id}: {e}")
            continue
    
    print(f"✅ Recálculo completado: {updated_count}/{total_count} transacciones actualizadas.")

if __name__ == "__main__":
    try:
        recalculate_profits()
    except KeyboardInterrupt:
        print("\n❌ Recálculo cancelado por el usuario.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error durante el recálculo: {e}")
        sys.exit(1)
