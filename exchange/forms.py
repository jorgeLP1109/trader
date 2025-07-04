# exchange/forms.py

from django import forms
from .models import AdvancedTransaction

class AdvancedTransactionForm(forms.ModelForm):
    class Meta:
        model = AdvancedTransaction
        # Excluimos los campos que se calculan o asignan automáticamente
        exclude = ['client', 'operator', 'amount_out', 'profit', 'created_at']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Etiquetas iniciales por defecto
        self.fields['amount_in'].label = "Monto de Entrada"
        self.fields['rate_or_fee'].label = "Tasa o Porcentaje"
        
        # Añadir IDs para que el JavaScript pueda encontrarlos
        self.fields['operation_type'].widget.attrs.update({'id': 'id_operation_type'})
        self.fields['amount_in'].widget.attrs.update({'id': 'id_amount_in'})
        self.fields['rate_or_fee'].widget.attrs.update({'id': 'id_rate_or_fee'})