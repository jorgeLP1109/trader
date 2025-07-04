# exchange/decorators.py

from django.shortcuts import render
from functools import wraps

def admin_required(function):
    """
    Decorador que comprueba si el usuario es un administrador autenticado.
    
    Si CUMPLE la condición: ejecuta la función de la vista normalmente.
    Si NO CUMPLE la condición: renderiza directamente la plantilla 403.html
    y detiene la ejecución.
    """
    @wraps(function)
    def wrap(request, *args, **kwargs):
        # La condición es la misma de antes
        if request.user.is_authenticated and request.user.role == 'admin':
            # Si el usuario es un admin, permite que la vista continúe
            return function(request, *args, **kwargs)
        else:
            # Si no es un admin, renderizamos nuestra plantilla de error
            # y detenemos todo lo demás.
            return render(request, '403.html', status=403)
            
    return wrap