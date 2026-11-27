"""Criação do cliente Firestore a partir de Application Default Credentials."""

from src.config import MarketSettings, load_settings


def get_client(settings: MarketSettings | None = None):
    """Cria um ``firestore.Client`` usando ADC.

    O import é feito dentro da função para não exigir a dependência em testes de
    módulos que não persistem. Exceções de credencial propagam para o chamador.
    """
    import google.auth
    from google.cloud import firestore

    settings = settings or load_settings(resolve_adc_project=False)
    credentials, default_project = google.auth.default()
    project = settings.google_cloud_project or default_project
    return firestore.Client(
        project=project,
        database=settings.firestore_database,
        credentials=credentials,
    )
