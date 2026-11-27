import pytest
from google.api_core.exceptions import PermissionDenied, ServiceUnavailable

from app.tests.market_fakes import FakeFirestoreClient
from src.config import load_settings
from src.storage.batch_writer import BatchedWriter
from src.storage.firestore_client import get_client
from src.utils import retry as retry_module


def _reference(client, index):
    return client.collection("teste").document(str(index))


def test_501_escritas_geram_dois_commits():
    client = FakeFirestoreClient()
    writer = BatchedWriter(client, batch_size=500)
    for index in range(501):
        writer.set(_reference(client, index), {"valor": index})
    writer.flush()
    assert client.commit_count == 2
    assert client.write_count == 501


def test_merge_false_e_rejeitado():
    client = FakeFirestoreClient()
    writer = BatchedWriter(client)
    with pytest.raises(ValueError, match="Toda escrita deve usar merge=True."):
        writer.set(_reference(client, 1), {"valor": 1}, merge=False)


def test_excecao_no_contexto_nao_faz_flush():
    client = FakeFirestoreClient()
    with pytest.raises(RuntimeError):
        with BatchedWriter(client, batch_size=10) as writer:
            writer.set(_reference(client, 1), {"valor": 1})
            raise RuntimeError("falha")
    assert client.commit_count == 0
    assert client.write_count == 0


def test_get_client_usa_projeto_e_banco_do_adc(monkeypatch):
    import google.auth
    from google.cloud import firestore

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(google.auth, "default", lambda: ("credenciais", "adc-project"))
    monkeypatch.setattr(firestore, "Client", FakeClient)

    settings = load_settings(env={}, resolve_adc_project=False)
    get_client(settings)

    assert captured["project"] == "adc-project"
    assert captured["database"] == "(default)"
    assert captured["credentials"] == "credenciais"


def test_get_client_prioriza_projeto_configurado(monkeypatch):
    import google.auth
    from google.cloud import firestore

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(google.auth, "default", lambda: ("credenciais", "adc-project"))
    monkeypatch.setattr(firestore, "Client", FakeClient)

    settings = load_settings(
        env={"GOOGLE_CLOUD_PROJECT": "explicito"}, resolve_adc_project=False
    )
    get_client(settings)
    assert captured["project"] == "explicito"


def test_retry_regete_service_unavailable(monkeypatch):
    monkeypatch.setattr(retry_module.time, "sleep", lambda _: None)
    client = FakeFirestoreClient()
    writer = BatchedWriter(client, batch_size=10, base_delay=0.001)
    writer.set(_reference(client, 1), {"valor": 1})
    writer._batch.failures = [ServiceUnavailable("temporário")]
    writer.flush()
    assert client.commit_count == 1


def test_retry_nao_regete_permission_denied(monkeypatch):
    monkeypatch.setattr(retry_module.time, "sleep", lambda _: None)
    client = FakeFirestoreClient()
    writer = BatchedWriter(client, batch_size=10, base_delay=0.001)
    writer.set(_reference(client, 1), {"valor": 1})
    writer._batch.failures = [PermissionDenied("negado")]
    with pytest.raises(PermissionDenied):
        writer.flush()
    assert client.commit_count == 0


def test_pending_e_flush_sem_operacoes():
    client = FakeFirestoreClient()
    writer = BatchedWriter(client, batch_size=10)
    assert writer.pending == 0
    writer.flush()
    assert client.commit_count == 0
    writer.set(_reference(client, 1), {"valor": 1})
    assert writer.pending == 1


def test_batch_size_e_limitado_entre_1_e_500():
    client = FakeFirestoreClient()
    assert BatchedWriter(client, batch_size=999)._batch_size == 500
    assert BatchedWriter(client, batch_size=0)._batch_size == 1


def test_context_manager_commita_no_sucesso():
    client = FakeFirestoreClient()
    with BatchedWriter(client, batch_size=10) as writer:
        writer.set(_reference(client, 1), {"valor": 1})
    assert client.commit_count == 1
    assert client.data["teste/1"] == {"valor": 1}


def test_retry_esgota_tentativas(monkeypatch):
    monkeypatch.setattr(retry_module.time, "sleep", lambda _: None)
    client = FakeFirestoreClient()
    writer = BatchedWriter(client, batch_size=10, max_retries=2, base_delay=0.001)
    writer.set(_reference(client, 1), {"valor": 1})
    writer._batch.failures = [ServiceUnavailable("1"), ServiceUnavailable("2")]
    with pytest.raises(ServiceUnavailable):
        writer.flush()
    assert client.commit_count == 0

