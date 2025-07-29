# config/config/urls.py

from django.contrib import admin
from django.urls import path, include
from exchange.views import custom_permission_denied_view

urlpatterns = [
    # 1. URLs del panel de administración de Django
    path('admin/', admin.site.urls),
    
    # 2. URLs de autenticación de Django (para login, logout, etc.)
    path('accounts/', include('django.contrib.auth.urls')),
    
    # 3. El resto del tráfico se delega a las URLs de nuestra aplicación 'exchange'
    path('', include('exchange.urls')),
]

# Definición del manejador de errores 403 (Permiso Denegado)
handler403 = custom_permission_denied_view