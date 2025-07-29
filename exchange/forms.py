# exchange/forms.py

from django import forms
from .models import AdvancedTransaction
from .models import VaultAdjustment 

# exchange/forms.py

class AdvancedTransactionForm(forms.ModelForm):
    class Meta:
        model = AdvancedTransaction
        # Eliminamos 'base_rate' y los campos autocalculados
        fields = ['operation_type', 'status', 'amount_in', 'rate_or_fee', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Añade cualquier nota relevante aquí...'}),
        }
        help_texts = {
            'operation_type': 'Selecciona el tipo de operación para ajustar los campos de abajo.',
            'rate_or_fee': 'Para tasas, usa punto decimal (ej. 125.50). Para comisiones, introduce solo el número (ej. 15 para 15%).',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fields['amount_in'].label = "Monto de Entrada"
        self.fields['amount_in'].widget.attrs.update({'placeholder': 'Ej: 100.00'})
        
        self.fields['rate_or_fee'].label = "Tasa de Operación / Fee (%)"
        self.fields['rate_or_fee'].widget.attrs.update({'placeholder': 'Ej: 125.50 o 15'})

        self.fields['operation_type'].widget.attrs.update({'id': 'id_operation_type'})
        self.fields['amount_in'].widget.attrs.update({'id': 'id_amount_in'})
        self.fields['rate_or_fee'].widget.attrs.update({'id': 'id_rate_or_fee'})


class VaultAdjustmentForm(forms.ModelForm):
    class Meta:
        model = VaultAdjustment
        fields = ['adjustment_type', 'amount_usd', 'amount_bs', 'amount_usdt', 'amount_zelle', 'reason']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Sea muy específico con el motivo del ajuste.'}),
        }
        help_texts = {
            'amount_usd': 'Use números positivos para inyecciones/correcciones, negativos para retiros.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hacemos que los campos no sean obligatorios, ya que se puede ajustar una sola moneda
        self.fields['amount_usd'].required = False
        self.fields['amount_bs'].required = False
        self.fields['amount_usdt'].required = False
        self.fields['amount_zelle'].required = False


class ResetDataForm(forms.Form):
    password = forms.CharField(
        label="Confirma tu contraseña de administrador", 
        widget=forms.PasswordInput,
        help_text="Esta acción es irreversible y borrará todos los datos transaccionales."
    )        
