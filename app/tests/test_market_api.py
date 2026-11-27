from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError

from app.api import routes
from app.main import app
from src.config import ConfigurationError
from datetime import date


QUOTE = {
    "data": "2024-01-02",
    "open": 35.1,
    "high": 35.5,
    "low": 34.9,
    "close": 35.2,
    "adj_close": 35.2,
    "volume": 12345678,
}
EVENTO = {
    "evento_id": "ITUB4_DIVIDENDO_2024-05-20_0.450000",
    "ticker": "ITUB4",
    "tipo_provento": "DIVIDENDO",
    "data_com": "2024-05-20",
    "data_ex": "2024-05-17",
    "data_pagamento": "2024-05-24",
    "valor_bruto": 0.45,
    "fonte": "B3",
}


def _client(monkeypatch, cotacoes=None, proventos=None):
    monkeypatch.setattr(
        routes,
        "load_settings",
        lambda **kwargs: SimpleNamespace(years=5, max_range_days=3650),
    )
    monkeypatch.setattr(
        routes.market_repository,
        "get_cotacoes",
        lambda *args, **kwargs: [QUOTE] if cotacoes is None else cotacoes,
    )
    monkeypatch.setattr(
        routes.market_repository,
        "get_proventos",
        lambda *args, **kwargs: [EVENTO] if proventos is None else proventos,
    )
    return TestClient(app)


def test_market_endpoint_200(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/v1/market/itub4?inicio=2024-01-01&fim=2024-12-31")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "ITUB4"
    assert payload["inicio"] == "2024-01-01"
    assert payload["fim"] == "2024-12-31"
    assert payload["cotacoes"] == [QUOTE]
    assert payload["proventos"] == [EVENTO]
    assert payload["avisos"] == []


def test_market_endpoint_ticker_invalido(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/v1/market/PETR")
    assert response.status_code == 400
    assert "ticker válido" in response.json()["detail"]


def test_market_endpoint_inicio_maior_que_fim(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/v1/market/ITUB4?inicio=2024-12-31&fim=2024-01-01")
    assert response.status_code == 400
    assert response.json()["detail"] == "A data inicial não pode ser posterior à data final."


def test_market_endpoint_intervalo_acima_do_limite(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/v1/market/ITUB4?inicio=2010-01-01&fim=2024-01-01")
    assert response.status_code == 400
    assert response.json()["detail"] == "O intervalo máximo permitido é de 3650 dias."


def test_market_endpoint_erro_de_firestore_vira_503(monkeypatch):
    client = _client(monkeypatch)

    def explode(*args, **kwargs):
        raise GoogleAPICallError("falha")

    monkeypatch.setattr(routes.market_repository, "get_cotacoes", explode)
    response = client.get("/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31")
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Não foi possível consultar o histórico de mercado no momento."
    )


def test_market_endpoint_listas_vazias_gera_avisos(monkeypatch):
    client = _client(monkeypatch, cotacoes=[], proventos=[])
    response = client.get("/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31")
    assert response.status_code == 200
    assert response.json()["avisos"] == [
        "Nenhuma cotação encontrada para o período informado.",
        "Nenhum provento encontrado para o período informado.",
        "Nenhum dado encontrado para o período informado.",
    ]


def test_market_endpoint_incluir_cotacoes_false(monkeypatch):
    client = _client(monkeypatch, cotacoes=[], proventos=[EVENTO])
    chamadas = []
    monkeypatch.setattr(
        routes.market_repository,
        "get_cotacoes",
        lambda *args, **kwargs: chamadas.append(args) or [],
    )
    response = client.get(
        "/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31&incluir_cotacoes=false"
    )
    assert response.status_code == 200
    assert chamadas == []
    assert response.json()["cotacoes"] == []
    assert response.json()["avisos"] == []


def test_market_endpoint_aviso_de_fonte_yahoo(monkeypatch):
    evento = dict(EVENTO)
    evento["fonte"] = "Yahoo Finance (data ex como data_com)"
    client = _client(monkeypatch, proventos=[evento])
    response = client.get("/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31")
    assert response.status_code == 200
    assert response.json()["avisos"] == [
        "Proventos obtidos do Yahoo Finance: data_com igual à data ex e "
        "data_pagamento indisponível."
    ]


def test_market_endpoint_incluir_proventos_false(monkeypatch):
    client = _client(monkeypatch, cotacoes=[QUOTE], proventos=[])
    chamadas = []
    monkeypatch.setattr(
        routes.market_repository,
        "get_proventos",
        lambda *args, **kwargs: chamadas.append(args) or [],
    )
    response = client.get(
        "/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31&incluir_proventos=false"
    )
    assert response.status_code == 200
    assert chamadas == []
    assert response.json()["proventos"] == []
    assert response.json()["avisos"] == []


def test_market_endpoint_janela_padrao_29_de_fevereiro(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(routes, "today_b3", lambda: date(2024, 2, 29))
    captured = {}

    def fake_cotacoes(*args, **kwargs):
        captured["args"] = args
        return [QUOTE]

    monkeypatch.setattr(routes.market_repository, "get_cotacoes", fake_cotacoes)
    response = client.get("/api/v1/market/ITUB4")

    assert response.status_code == 200
    assert response.json()["inicio"] == "2019-02-28"
    assert response.json()["fim"] == "2024-02-29"
    assert captured["args"][1] == "2019-02-28"
    assert captured["args"][2] == "2024-02-29"


def test_market_endpoint_configuracao_invalida_vira_503(monkeypatch):
    client = _client(monkeypatch)

    def explode(**kwargs):
        raise ConfigurationError("config ruim")

    monkeypatch.setattr(routes, "load_settings", explode)
    response = client.get("/api/v1/market/ITUB4")
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Não foi possível consultar o histórico de mercado no momento."
    )


def test_market_endpoint_credenciais_indisponiveis_vira_503(monkeypatch):
    client = _client(monkeypatch)

    def explode(*args, **kwargs):
        raise DefaultCredentialsError("sem credenciais")

    monkeypatch.setattr(routes.market_repository, "get_cotacoes", explode)
    response = client.get("/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31")
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Não foi possível consultar o histórico de mercado no momento."
    )


def test_market_endpoint_value_error_do_repositorio_vira_400(monkeypatch):
    client = _client(monkeypatch)

    def explode(*args, **kwargs):
        raise ValueError("data inválida")

    monkeypatch.setattr(routes.market_repository, "get_cotacoes", explode)
    response = client.get("/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31")
    assert response.status_code == 400
    assert response.json()["detail"] == "data inválida"

