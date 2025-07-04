# exchange/apps.py

from django.apps import AppConfig

class ExchangeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'exchange'

    def ready(self):
        """
        Este método se ejecuta cuando la aplicación está lista.
        Es el lugar ideal para importar y registrar las señales.
        """
        import exchange.models # Importamos los modelos para que las señales se registren