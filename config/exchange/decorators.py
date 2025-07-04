# exchange/decorators.py (Archivo nuevo)

from django.core.exceptions import PermissionDenied
from functools import wraps

def admin_required(function):
    """
    Decorador que comprueba si el usuario está logueado y tiene el rol 'admin'.
    Si no cumple, lanza una excepción PermissionDenied.
    """
    @wraps(function)
    def wrap(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role == 'admin':
            return function(request, *args, **kwargs)
        else:
            # Esta excepción será capturada por nuestro handler403
            raise PermissionDenied
    return wrap