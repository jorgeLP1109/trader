# exchange/views_reports.py
# Nuevas vistas optimizadas para reportes de ganancias y pérdidas

from django.shortcuts import render
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.paginator import Paginator
from django.http import JsonResponse
from .models import AdvancedTransaction, Client, CashVault
from .views import AdminRequiredMixin


class ProfitLossReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    """
    Reporte optimizado de Ganancias y Pérdidas sin información de deudas.
    Enfocado en mostrar claramente la rentabilidad del negocio.
    """
    template_name = 'exchange/reports/profit_loss_report.html'
    
    def get(self, request, *args, **kwargs):
        # --- 1. FILTROS ---
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        operation_filter = request.GET.get('operation_type', '')
        client_filter = request.GET.get('client_id', '')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # --- 2. QUERYSET BASE (Solo transacciones completadas) ---
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('client', 'operator').order_by('-created_at')
        
        # Aplicar filtros adicionales
        if operation_filter:
            transactions_qs = transactions_qs.filter(operation_type=operation_filter)
        if client_filter and client_filter.isdigit():
            transactions_qs = transactions_qs.filter(client_id=client_filter)
        
        # --- 3. CÁLCULOS DE RESUMEN ---
        # Ganancias por tipo usando los nuevos campos mejorados
        profit_by_commission = transactions_qs.filter(
            operation_type__in=['USDT_FOR_CASH', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
        ).aggregate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            count=Count('id'),
            avg_profit_usd=Avg('profit_usd_equivalent')
        )
        
        profit_by_spread = transactions_qs.filter(
            operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']
        ).aggregate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            count=Count('id'),
            avg_profit_usd=Avg('profit_usd_equivalent')
        )
        
        # Volúmenes de operación
        volumes = {
            'total_usd_moved': transactions_qs.filter(
                operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
            ).aggregate(total=Sum('amount_in'))['total'] or Decimal('0.00'),
            
            'total_usdt_moved': transactions_qs.filter(
                operation_type__in=['USDT_FOR_CASH', 'USDT_FOR_BS']
            ).aggregate(total=Sum('amount_in'))['total'] or Decimal('0.00'),
            
            'total_bs_moved': transactions_qs.filter(
                operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'USDT_FOR_BS']
            ).aggregate(total=Sum('amount_out'))['total'] or Decimal('0.00'),
        }
        
        # Métricas de rentabilidad usando campos mejorados
        total_profit_usd = (
            (profit_by_commission['total_profit_usd'] or Decimal('0.00')) +
            (profit_by_spread['total_profit_usd'] or Decimal('0.00'))
        )
        
        total_profit_bs = (
            (profit_by_commission['total_profit_bs'] or Decimal('0.00')) +
            (profit_by_spread['total_profit_bs'] or Decimal('0.00'))
        )
        
        # Totales ya calculados con equivalencias
        total_profit_bs_equivalent = total_profit_bs
        
        # --- 4. ANÁLISIS POR PERÍODO ---
        # Ganancias por día de la semana usando campos mejorados
        daily_profits = []
        current_date = start_date
        while current_date <= end_date:
            day_transactions = transactions_qs.filter(created_at__date=current_date)
            day_profit_usd = day_transactions.aggregate(total=Sum('profit_usd_equivalent'))['total'] or Decimal('0.00')
            day_profit_bs = day_transactions.aggregate(total=Sum('profit_bs_equivalent'))['total'] or Decimal('0.00')
            daily_profits.append({
                'date': current_date,
                'profit_usd': day_profit_usd,
                'profit_bs': day_profit_bs,
                'transactions_count': day_transactions.count()
            })
            current_date += timedelta(days=1)
        
        # --- 5. TOP CLIENTES POR RENTABILIDAD ---
        top_clients = transactions_qs.values(
            'client__name', 'client__id'
        ).annotate(
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            total_transactions=Count('id'),
            total_volume=Sum('amount_primary')
        ).order_by('-total_profit_usd')[:10]
        
        # --- 6. PAGINACIÓN ---
        paginator = Paginator(transactions_qs, 25)
        page_obj = paginator.get_page(request.GET.get('page'))
        
        context = {
            'page_title': 'Reporte de Ganancias y Pérdidas',
            'start_date': start_date,
            'end_date': end_date,
            'transactions': page_obj,
            'is_paginated': True,
            'page_obj': page_obj,
            
            # Resumen financiero
            'financial_summary': {
                'total_profit_usd': total_profit_usd,
                'total_profit_bs': total_profit_bs,
                'total_profit_bs_equivalent': total_profit_bs_equivalent,
                'total_transactions': transactions_qs.count(),
                'avg_profit_per_transaction': total_profit_bs_equivalent / max(transactions_qs.count(), 1),
            },
            
            # Análisis por tipo de operación
            'operation_analysis': {
                'commission_operations': {
                    'count': profit_by_commission['count'] or 0,
                    'total_profit_usd': profit_by_commission['total_profit_usd'] or Decimal('0.00'),
                    'total_profit_bs': profit_by_commission['total_profit_bs'] or Decimal('0.00'),
                    'avg_profit_usd': profit_by_commission['avg_profit_usd'] or Decimal('0.00'),
                },
                'spread_operations': {
                    'count': profit_by_spread['count'] or 0,
                    'total_profit_usd': profit_by_spread['total_profit_usd'] or Decimal('0.00'),
                    'total_profit_bs': profit_by_spread['total_profit_bs'] or Decimal('0.00'),
                    'avg_profit_usd': profit_by_spread['avg_profit_usd'] or Decimal('0.00'),
                }
            },
            
            'volumes': volumes,
            'daily_profits': daily_profits,
            'top_clients': top_clients,
            
            # Filtros para el template
            'operation_choices': AdvancedTransaction.OPERATION_CHOICES,
            'selected_operation': operation_filter,
            'clients': Client.objects.all().order_by('name'),
            'selected_client': int(client_filter) if client_filter.isdigit() else None,
        }
        
        return render(request, self.template_name, context)


class TransactionsByClientReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    """
    Reporte simplificado que muestra claramente quién compró dólares, 
    quién compró bolívares y cuándo, sin información de deudas.
    """
    template_name = 'exchange/reports/transactions_by_client_report.html'
    
    def get(self, request, *args, **kwargs):
        # --- 1. FILTROS ---
        today = timezone.localdate()
        start_date_str = request.GET.get('start_date', today.replace(day=1).strftime('%Y-%m-%d'))
        end_date_str = request.GET.get('end_date', today.strftime('%Y-%m-%d'))
        client_filter = request.GET.get('client_id', '')
        transaction_type = request.GET.get('transaction_type', '')  # 'buy_usd', 'sell_usd', 'all'
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # --- 2. QUERYSET BASE ---
        transactions_qs = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('client', 'operator').order_by('-created_at')
        
        # Filtro por cliente
        if client_filter and client_filter.isdigit():
            transactions_qs = transactions_qs.filter(client_id=client_filter)
        
        # Filtro por tipo de transacción
        if transaction_type == 'buy_usd':
            # Cliente compra dólares (nosotros vendemos)
            transactions_qs = transactions_qs.filter(
                operation_type__in=['SELL_USD_FOR_BS', 'USDT_FOR_CASH', 'ZELLE_FOR_CASH']
            )
        elif transaction_type == 'sell_usd':
            # Cliente vende dólares (nosotros compramos)
            transactions_qs = transactions_qs.filter(
                operation_type__in=['BUY_USD_FOR_BS', 'CASH_FOR_USDT']
            )
        
        # --- 3. PROCESAMIENTO DE TRANSACCIONES ---
        processed_transactions = []
        for tx in transactions_qs:
            # Determinar qué compró/vendió el cliente (usando amount_primary como referencia del monto principal)
            if tx.operation_type in ['SELL_USD_FOR_BS']:
                # Cliente COMPRÓ USD, pagó con BS
                client_action = f"Compró ${tx.amount_primary} USD"
                client_paid = f"{tx.amount_in:,.2f} Bs"
            
            elif tx.operation_type in ['BUY_USD_FOR_BS']:
                # Cliente VENDIÓ USD, recibió BS
                client_action = f"Vendió ${tx.amount_primary} USD"
                client_paid = f"Recibió {tx.amount_in:,.2f} Bs"
            
            elif tx.operation_type in ['USDT_FOR_CASH', 'ZELLE_FOR_CASH']:
                # Cliente COMPRÓ USD, pagó con USDT/Zelle
                client_action = f"Compró ${tx.amount_out} USD"
                client_paid = f"Dio {tx.amount_primary} USDT/Zelle"
            
            elif tx.operation_type in ['CASH_FOR_USDT']:
                # Cliente COMPRÓ USDT, pagó con USD
                client_action = f"Compró {tx.amount_out} USDT"
                client_paid = f"${tx.amount_primary}"
            
            elif tx.operation_type in ['USDT_FOR_BS']:
                # Cliente VENDIÓ USDT, recibió BS
                client_action = f"Vendió {tx.amount_primary} USDT"
                client_paid = f"Recibió {tx.amount_in:,.2f} Bs"
            
            else:
                client_action = "Operación especial"
                client_paid = "N/A"
            
            # Usar el método mejorado para mostrar ganancias
            our_gain = tx.get_profit_display()
            
            processed_transactions.append({
                'transaction': tx,
                'client_action': client_action,
                'client_paid': client_paid,
                'our_gain': our_gain,
                'rate_used': tx.rate_or_fee
            })
        
        # --- 4. RESUMEN POR CLIENTE ---
        client_summaries = transactions_qs.values(
            'client__name', 'client__id'
        ).annotate(
            total_transactions=Count('id'),
            total_profit_usd=Sum('profit_usd_equivalent'),
            total_profit_bs=Sum('profit_bs_equivalent'),
            total_volume_usd=Sum('amount_primary', filter=Q(
                operation_type__in=['SELL_USD_FOR_BS', 'BUY_USD_FOR_BS', 'CASH_FOR_USDT', 'ZELLE_FOR_CASH']
            )),
            total_volume_usdt=Sum('amount_primary', filter=Q(
                operation_type__in=['USDT_FOR_CASH', 'USDT_FOR_BS']
            ))
        ).order_by('-total_profit_usd')
        
        # --- 5. PAGINACIÓN ---
        paginator = Paginator(processed_transactions, 30)
        page_obj = paginator.get_page(request.GET.get('page'))
        
        context = {
            'page_title': 'Reporte de Transacciones por Cliente',
            'start_date': start_date,
            'end_date': end_date,
            'processed_transactions': page_obj,
            'is_paginated': True,
            'page_obj': page_obj,
            
            'client_summaries': client_summaries,
            'total_unique_clients': client_summaries.count(),
            
            # Filtros
            'clients': Client.objects.all().order_by('name'),
            'selected_client': int(client_filter) if client_filter.isdigit() else None,
            'transaction_types': [
                ('all', 'Todas las operaciones'),
                ('buy_usd', 'Clientes que compraron USD/USDT'),
                ('sell_usd', 'Clientes que vendieron USD/USDT'),
            ],
            'selected_transaction_type': transaction_type,
        }
        
        return render(request, self.template_name, context)


class DashboardMetricsAPIView(LoginRequiredMixin, View):
    """
    API para métricas del dashboard sin información de deudas
    """
    def get(self, request):
        # Período para métricas (últimos 30 días)
        end_date = timezone.localdate()
        start_date = end_date - timedelta(days=30)
        
        # Transacciones del período
        recent_transactions = AdvancedTransaction.objects.filter(
            status='completed',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )
        
        # Métricas principales usando campos mejorados
        total_profit_usd = recent_transactions.aggregate(total=Sum('profit_usd_equivalent'))['total'] or 0
        total_profit_bs = recent_transactions.aggregate(total=Sum('profit_bs_equivalent'))['total'] or 0
        
        metrics = {
            'total_profit_last_30_days_usd': float(total_profit_usd),
            'total_profit_last_30_days_bs': float(total_profit_bs),
            
            'transactions_last_30_days': recent_transactions.count(),
            
            'avg_daily_profit_usd': float(total_profit_usd) / 30,
            'avg_daily_profit_bs': float(total_profit_bs) / 30,
            
            'top_operation_type': recent_transactions.values(
                'operation_type'
            ).annotate(
                count=Count('id')
            ).order_by('-count').first(),
            
            'profit_trend': self._get_profit_trend(recent_transactions),
        }
        
        return JsonResponse(metrics)
    
    def _get_profit_trend(self, transactions_qs):
        """Calcula tendencia de ganancias de los últimos 7 días usando campos mejorados"""
        trend_data = []
        for i in range(7):
            date = timezone.localdate() - timedelta(days=i)
            day_transactions = transactions_qs.filter(created_at__date=date)
            
            day_profit_usd = day_transactions.aggregate(total=Sum('profit_usd_equivalent'))['total'] or 0
            day_profit_bs = day_transactions.aggregate(total=Sum('profit_bs_equivalent'))['total'] or 0
            
            trend_data.append({
                'date': date.strftime('%Y-%m-%d'),
                'profit_usd': float(day_profit_usd),
                'profit_bs': float(day_profit_bs)
            })
        
        return list(reversed(trend_data))
