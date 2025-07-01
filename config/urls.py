# config/urls.py

from django.contrib import admin
from django.urls import path, include # <-- Asegúrate de que 'include' esté importado

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('exchange.urls')), # <-- AGREGA ESTA LÍNEA
]