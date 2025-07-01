# exchange/forms.py

from django import forms
from .models import Transaction

class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        # Usamos los nombres de campo nuevos y correctos del modelo Transaction
        fields = ['operation_type', 'amount_usd', 'exchange_rate', 'status', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Añadimos los IDs y el evento onkeyup para que el JavaScript funcione
        # y calcule el total en tiempo real.
        self.fields['amount_usd'].widget.attrs.update({
            'id': 'id_amount_usd', 
            'onkeyup': 'calculateTotal()',
            'autocomplete': 'off' # Evita que el navegador sugiera valores
        })
        self.fields['exchange_rate'].widget.attrs.update({
            'id': 'id_exchange_rate', 
            'onkeyup': 'calculateTotal()',
            'autocomplete': 'off'
        })