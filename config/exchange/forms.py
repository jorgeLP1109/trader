# exchange/forms.py

from django import forms
from .models import AdvancedTransaction

class AdvancedTransactionForm(forms.ModelForm):
    class Meta:
        model = AdvancedTransaction
        exclude = ['client', 'operator', 'amount_out', 'profit', 'created_at']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Añade cualquier nota relevante aquí...'}),
        }
        # Textos de ayuda que aparecerán debajo de los campos
        help_texts = {
            'operation_type': 'Selecciona el tipo de operación para ajustar los campos de abajo.',
            'rate_or_fee': 'Para tasas, usa punto decimal (ej. 125.50). Para comisiones, introduce solo el número (ej. 1.5 para 1.5%).',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Etiquetas y placeholders iniciales
        self.fields['amount_in'].label = "Monto de Entrada"
        self.fields['amount_in'].widget.attrs.update({'placeholder': 'Ej: 100.00'})
        
        self.fields['rate_or_fee'].label = "Tasa o Porcentaje"
        self.fields['rate_or_fee'].widget.attrs.update({'placeholder': 'Ej: 125.50 o 1.5'})

        # IDs para el JavaScript
        self.fields['operation_type'].widget.attrs.update({'id': 'id_operation_type'})
        self.fields['amount_in'].widget.attrs.update({'id': 'id_amount_in'})
        self.fields['rate_or_fee'].widget.attrs.update({'id': 'id_rate_or_fee'})