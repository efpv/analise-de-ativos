import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import httpx
import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.api import routes
from app.services import api_client
from app.models.valuation import AssetData, DividendPayment
from app.services.valuation_service import ValuationService


def test_home_page(monkeypatch):
    monkeypatch.setattr(routes, "settings", SimpleNamespace(ranking_enabled=False))
    client = TestClient(app)
    response = client.get("/calculadora")
    assert response.status_code == 200
    assert "Preço Justo Bazin" in response.text
    assert "Dados utilizados no cálculo" in response.text
    assert "Ranking Bazin" in response.text
    assert response.text.index('id="comparacao"') < response.text.index('id="ranking"')
    assert '<a href="/ranking" hidden>' in response.text
    assert 'id="ranking" class="page-section dashboard-section" hidden' in response.text
    assert "O Ranking Bazin está temporariamente desativado" not in response.text


def test_ranking_page():
    response = TestClient(app).get("/ranking")
    assert response.status_code == 200
    assert "ranking-body" in response.text


def test_catalogo_de_ativos_serve_json_local(monkeypatch):
    def unexpected_lookup(ticker):
        pytest.fail("O catálogo não deve consultar provedores")

    monkeypatch.setattr(routes.ticker_service, "get_asset", unexpected_lookup)
    response = TestClient(app).get("/api/v1/assets")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assets = response.json()
    assert any(item["ticker"] == "PETR4" and item["symbol"] == "PETR4.SA" for item in assets)
    assert any(item["ticker"] == "BBAS3" and item["company"] for item in assets)


def test_enabled_ranking_is_visible(monkeypatch):
    monkeypatch.setattr(routes, "settings", SimpleNamespace(ranking_enabled=True))
    response = TestClient(app).get("/calculadora")
    assert 'id="ranking" class="page-section dashboard-section">' in response.text
    assert '<a href="/ranking">Ranking Bazin</a>' in response.text
    assert "O Ranking Bazin está temporariamente desativado" not in response.text


def test_disabled_ranking_does_not_calculate_assets(monkeypatch):
    monkeypatch.setattr(routes, "settings", SimpleNamespace(ranking_enabled=False))

    def unexpected_calculation(*args):
        pytest.fail("Ranking desativado não deve consultar ativos")

    monkeypatch.setattr(routes, "_calculate", unexpected_calculation)
    response = TestClient(app).get("/api/v1/ranking")
    assert response.status_code == 503
    assert "temporariamente desativado" in response.json()["detail"]


def test_invalid_ticker_endpoint():
    client = TestClient(app)
    response = client.get("/api/v1/valuation/PETR")
    assert response.status_code == 400
    assert "ticker válido" in response.json()["detail"]


def test_api_normalize_dividend_yield():
    assert api_client.ApiClient._normalize_yield(0.075) == 7.5
    assert api_client.ApiClient._normalize_yield(7.5) == 7.5
    assert api_client.ApiClient._normalize_yield(None) is None
    assert api_client.ApiClient._normalize_yield("invalid") is None
    assert api_client.ApiClient._normalize_yield(-0.2) is None


def test_api_aggregate_dividends():
    client = api_client.ApiClient()
    history = client._aggregate_dividends([
        {"paymentDate": "2025-03-01", "value": 1.0},
        {"paymentDate": "2025-09-01", "value": 0.5},
        {"paymentDate": "2024-05-01", "amount": 2.0},
    ])
    assert sum(history.values()) >= 3.5


def test_brapi_parses_asset(monkeypatch):
    payload = {
        "results": [{
            "regularMarketPrice": 25.42,
            "longName": "Banco do Brasil",
            "dividendYield": 0.075,
            "dividendsData": {"cashDividends": [
                {"paymentDate": "2025-01-01", "rate": 2.5},
            ]},
        }]
    }

    class MockResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    asset = asyncio.run(api_client.ApiClient()._from_brapi("BBAS3"))
    assert asset is not None
    assert asset.empresa == "Banco do Brasil"
    assert asset.preco_atual == 25.42
    assert asset.fonte == "BRAPI"
    assert asset.dividendos_historicos == {2025: 2.5}
    assert asset.pagamentos[0].valor == 2.5
    assert asset.eventos_encontrados == 1


@pytest.mark.parametrize("status", [401, 403, 429])
def test_brapi_http_failure_logs_status_without_sensitive_details(monkeypatch, caplog, status):
    client = api_client.ApiClient()
    request = httpx.Request("GET", "https://brapi.dev/api/quote/TAEE11?token=segredo")
    response = httpx.Response(status, request=request, text="segredo")

    async def brapi(ticker):
        raise httpx.HTTPStatusError("segredo", request=request, response=response)

    monkeypatch.setattr(client, "_from_brapi", brapi)
    monkeypatch.setattr(client, "_from_yahoo", lambda ticker: None)
    assert client.get_asset("TAEE11") is None
    assert f"ticker=TAEE11 status_http={status} tipo=HTTPStatusError" in caplog.text
    assert "Yahoo Finance não retornou dados válidos: ticker=TAEE11" in caplog.text
    assert "segredo" not in caplog.text
    assert any(record.status_http == status for record in caplog.records if hasattr(record, "status_http"))


def test_brapi_404_logs_status_before_fallback(monkeypatch, caplog):
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return httpx.Response(404)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    client = api_client.ApiClient()
    monkeypatch.setattr(client, "_from_yahoo", lambda ticker: None)
    assert client.get_asset("TAEE11") is None
    assert "BRAPI não retornou o ativo: ticker=TAEE11 status_http=404" in caplog.text


def test_provider_exceptions_log_types_without_messages(monkeypatch, caplog):
    client = api_client.ApiClient()

    async def brapi(ticker):
        raise httpx.ConnectTimeout("segredo")

    def yahoo(ticker):
        raise ValueError("segredo")

    monkeypatch.setattr(client, "_from_brapi", brapi)
    monkeypatch.setattr(client, "_from_yahoo", yahoo)
    assert client.get_asset("TAEE11") is None
    assert "BRAPI: ticker=TAEE11 tipo=ConnectTimeout" in caplog.text
    assert "Yahoo Finance: ticker=TAEE11 tipo=ValueError" in caplog.text
    assert "segredo" not in caplog.text


def test_valuation_response_includes_data_and_recalculated_yield(monkeypatch):
    asset = AssetData(
        ticker="BBAS3",
        empresa="Banco do Brasil",
        preco_atual=25,
        dividend_yield=7.5,
        dividendos_historicos={2021: 1, 2022: 1, 2023: 1, 2024: 1, 2025: 2},
        fonte="BRAPI",
    )
    valuation = ValuationService().calculate(asset)
    monkeypatch.setattr(routes, "_calculate", lambda ticker, taxa=None, periodo="5anos": valuation)
    monkeypatch.setattr(routes.repository, "add", lambda *args: None)

    response = TestClient(app).get("/api/v1/valuation/BBAS3")
    assert response.status_code == 200
    body = response.json()
    assert body["dividend_yield"] == 8
    assert body["fonte"] == "BRAPI"
    assert body["data_consulta"]
    assert isinstance(body["avisos"], list)
    assert len(body["dividendos_historicos"]) == 5
    assert body["setor"] == "Bancos"
    assert body["ativos_comparaveis"] == ["ITUB4", "BBDC4", "SANB11"]


def test_comparison_rejects_more_than_four_assets():
    response = TestClient(app).get(
        "/api/v1/comparison?tickers=ITSA4&tickers=BBAS3&tickers=TAEE11&tickers=BBSE3&tickers=PETR4"
    )
    assert response.status_code == 400
    assert "1 e 4" in response.json()["detail"]


def test_comparison_rejects_invalid_ticker():
    response = TestClient(app).get("/api/v1/comparison?tickers=INVALID")
    assert response.status_code == 400
    assert "ticker válido" in response.json()["detail"]


def test_ranking_sorts_by_requested_order(monkeypatch):
    monkeypatch.setattr(routes, "settings", SimpleNamespace(ranking_enabled=True))
    history = {2021: 1.0, 2022: 2.0, 2023: 3.0, 2024: 4.0, 2025: 5.0}
    prices = {"BBAS3": 20, "BBSE3": 40, "ITSA4": 50, "PETR4": 100}

    def fake_calculate(ticker, taxa=None, periodo="5anos"):
        return ValuationService().calculate(
            AssetData(ticker, ticker, prices.get(ticker, 60), None, history),
            taxa,
        )

    monkeypatch.setattr(routes, "_calculate", fake_calculate)
    response = TestClient(app).get("/api/v1/ranking?ordem=potencial")
    assert response.status_code == 200
    body = response.json()
    assert body["itens"][0]["ticker"] == "BBAS3"
    assert body["ordem"] == "potencial"
    assert body["avisos"] == []


@pytest.mark.parametrize("order", ["dy", "classificacao"])
def test_ranking_supports_all_other_orders(monkeypatch, order):
    monkeypatch.setattr(routes, "settings", SimpleNamespace(ranking_enabled=True))
    history = {2021: 1.0, 2022: 2.0, 2023: 3.0, 2024: 4.0, 2025: 5.0}
    prices = {"BBAS3": 20, "BBSE3": 40, "ITSA4": 50, "PETR4": 100}

    def fake_calculate(ticker, taxa=None, periodo="5anos"):
        return ValuationService().calculate(
            AssetData(ticker, ticker, prices.get(ticker, 60), None, history),
            taxa,
        )

    monkeypatch.setattr(routes, "_calculate", fake_calculate)
    response = TestClient(app).get(f"/api/v1/ranking?ordem={order}")
    assert response.status_code == 200
    assert response.json()["itens"][0]["ticker"] == "BBAS3"


def test_comparison_returns_valuations(monkeypatch):
    history = {2021: 1.0, 2022: 2.0, 2023: 3.0, 2024: 4.0, 2025: 5.0}

    def fake_calculate(ticker, taxa=None, periodo="5anos"):
        return ValuationService().calculate(
            AssetData(ticker, ticker, 30, None, history),
            taxa,
        )

    monkeypatch.setattr(routes, "_calculate", fake_calculate)
    response = TestClient(app).get(
        "/api/v1/comparison?tickers=ITSA4&tickers=BBAS3"
    )
    assert response.status_code == 200
    assert [item["ticker"] for item in response.json()["itens"]] == ["ITSA4", "BBAS3"]


def test_comparison_returns_available_assets_and_warnings(monkeypatch):
    history = {2021: 1.0, 2022: 2.0, 2023: 3.0, 2024: 4.0, 2025: 5.0}

    def fake_calculate(ticker, taxa=None, periodo="5anos"):
        if ticker == "BBAS3":
            raise LookupError("Ativo não encontrado.")
        return ValuationService().calculate(AssetData(ticker, ticker, 30, None, history), taxa)

    monkeypatch.setattr(routes, "_calculate", fake_calculate)
    response = TestClient(app).get(
        "/api/v1/comparison?tickers=ITSA4&tickers=BBAS3"
    )
    assert response.status_code == 200
    assert [item["ticker"] for item in response.json()["itens"]] == ["ITSA4"]
    assert response.json()["avisos"] == ["BBAS3: Ativo não encontrado."]


def test_periodo_e_taxa_propagados_na_api(monkeypatch):
    year = date.today().year
    asset = AssetData("BBAS3", "Banco", 20, None, {year - 5: 1, year - 3: 3, year - 2: 4, year - 1: 5})
    monkeypatch.setattr(routes.ticker_service, "get_asset", lambda ticker: asset)
    monkeypatch.setattr(routes.repository, "add", lambda *args: None)
    client = TestClient(app)
    response = client.get("/api/v1/valuation/BBAS3?periodo=3anos&taxa=0.1")
    assert response.status_code == 200
    body = response.json()
    assert body["periodo"] == "3anos"
    assert body["dividendos_medios"] == 4
    assert body["preco_justo"] == 40
    assert body["dividendos_ltm"] is None
    assert client.get("/api/v1/valuation/BBAS3?periodo=ltm").status_code == 400
    assert client.get("/api/v1/valuation/BBAS3?periodo=invalido").status_code == 422
    comparison = client.get("/api/v1/comparison?tickers=BBAS3&periodo=3anos&taxa=0.1")
    assert comparison.json()["itens"][0]["preco_justo"] == 40


def test_brapi_preserva_historico_e_exige_data_de_pagamento_para_ltm():
    client = api_client.ApiClient()
    today = date.today()
    history, warnings, payments, count = client._parse_dividends({"cashDividends": [
        {"paymentDate": today.isoformat(), "rate": 1.5},
        {"paymentDate": (today - timedelta(days=365 * 8)).isoformat(), "value": 2},
    ]})
    assert len(history) == 2
    assert len(payments) == 2
    assert count == 2
    assert warnings == []
    _, warnings, payments, _ = client._parse_dividends([
        {"date": today.isoformat(), "value": 1},
    ])
    assert payments is None
    assert any("pode estar incompleto" in warning for warning in warnings)
    history, _, payments, _ = client._parse_dividends([
        {"exDate": today.isoformat(), "rate": 1},
        {"paymentDate": today.isoformat(), "paymentDateIsDeadline": True, "rate": 2},
    ])
    assert history[today.year] == 3
    assert payments is None
    _, warnings, payments, _ = client._parse_dividends([
        {"paymentDate": today.isoformat(), "rate": 2},
        {"exDate": today.isoformat(), "rate": 1},
    ])
    assert len(payments) == 1
    assert any("pode estar incompleto" in warning for warning in warnings)


def test_ltm_api_devolve_pagamentos_e_soma(monkeypatch):
    today = date.today()
    asset = AssetData(
        "BBAS3", "Banco", 20, None, {today.year - 1: 4},
        pagamentos=(
            DividendPayment(today, 0.75),
            DividendPayment(today - timedelta(days=30), 1.25),
        ),
    )
    monkeypatch.setattr(routes.ticker_service, "get_asset", lambda ticker: asset)
    monkeypatch.setattr(routes.repository, "add", lambda *args: None)
    response = TestClient(app).get("/api/v1/valuation/BBAS3?periodo=ltm&taxa=0.1")
    assert response.status_code == 200
    body = response.json()
    assert body["dividendos_ltm"] == 2
    assert body["dividendos_medios"] == 2
    assert body["preco_justo"] == 20
    assert [payment["valor"] for payment in body["pagamentos_ltm"]] == [1.25, 0.75]
    assert body["resumo_dividendos"]["anos_analisados"] is None
    assert body["resumo_dividendos"]["maior_anual"] is None
    assert body["precos_perfil"]["moderado"] == 25


def test_fallback_quando_brapi_nao_retorna_dividendos(monkeypatch):
    client = api_client.ApiClient()
    empty = AssetData("PETR4", "Petrobras", 20, None, {}, fonte="BRAPI")
    yahoo = AssetData("PETR4", "Petrobras", 20, None, {date.today().year - 1: 2}, fonte="Yahoo Finance")

    async def brapi(ticker):
        return empty

    monkeypatch.setattr(client, "_from_brapi", brapi)
    monkeypatch.setattr(client, "_from_yahoo", lambda ticker: yahoo)
    assert client.get_asset("PETR4") == yahoo


def test_resumo_cenarios_e_situacao_dos_anos(monkeypatch):
    year = date.today().year
    asset = AssetData(
        "BBAS3", "Banco", 20, None,
        {year - 3: 2, year - 2: 3, year - 1: 6, year: 1, year + 1: 100},
        eventos_encontrados=5,
    )
    monkeypatch.setattr(routes.ticker_service, "get_asset", lambda ticker: asset)
    monkeypatch.setattr(routes.repository, "add", lambda *args: None)
    client = TestClient(app)
    body = client.get("/api/v1/valuation/BBAS3?periodo=3anos").json()
    assert body["eventos_encontrados"] == 5
    assert body["resumo_dividendos"] == {
        "anos_analisados": 3, "maior_anual": 6, "menor_anual": 2, "crescimento_medio": 75
    }
    assert body["precos_perfil"]["agressivo"] == pytest.approx((11 / 3) / 0.06)
    assert body["precos_perfil"]["moderado"] == pytest.approx((11 / 3) / 0.08)
    assert body["precos_perfil"]["conservador"] == pytest.approx((11 / 3) / 0.1)
    assert all(item["situacao"] == "encerrado" for item in body["dividendos_historicos"])
    all_years = client.get("/api/v1/valuation/BBAS3?periodo=todos").json()
    assert [item["ano"] for item in all_years["dividendos_historicos"]] == [year - 3, year - 2, year - 1, year]
    assert all_years["dividendos_historicos"][-1]["situacao"] == "parcial"
    assert any("podem estar incompletos" in warning for warning in all_years["avisos"])
    five = client.get("/api/v1/valuation/BBAS3?periodo=5anos").json()
    assert five["dividendos_historicos"][0]["situacao"] == "sem_registro"
    assert five["resumo_dividendos"]["crescimento_medio"] is None


def test_crescimento_indisponivel_quando_ultimo_ano_nao_tem_registro(monkeypatch):
    year = date.today().year
    asset = AssetData("BBAS3", "Banco", 20, None, {year - 3: 2, year - 2: 3})
    monkeypatch.setattr(routes.ticker_service, "get_asset", lambda ticker: asset)
    monkeypatch.setattr(routes.repository, "add", lambda *args: None)
    body = TestClient(app).get("/api/v1/valuation/BBAS3?periodo=3anos").json()
    assert body["dividendos_historicos"][-1]["situacao"] == "sem_registro"
    assert body["resumo_dividendos"]["crescimento_medio"] is None


def test_nao_inclui_pagamentos_futuros_no_historico_anual():
    today = date.today()
    future = today + timedelta(days=1)
    history, _, payments, count = api_client.ApiClient()._parse_dividends([
        {"paymentDate": today.isoformat(), "rate": 1},
        {"paymentDate": future.isoformat(), "rate": 10},
        {"paymentDate": "inválida", "rate": 100},
    ])
    assert sum(history.values()) == 1
    assert len(payments) == 2
    assert count == 2


def test_yahoo_conta_eventos_validos_sem_incluir_datas_futuras(monkeypatch):
    import yfinance

    today = date.today()
    events = [
        (datetime.combine(today, datetime.min.time()), 1),
        (datetime.combine(today + timedelta(days=1), datetime.min.time()), 2),
        (datetime.combine(today, datetime.min.time()), "inválido"),
    ]
    stock = SimpleNamespace(
        fast_info={"last_price": 20},
        info={"longName": "Empresa"},
        dividends=SimpleNamespace(items=lambda: events),
    )
    monkeypatch.setattr(yfinance, "Ticker", lambda ticker: stock)
    asset = api_client.ApiClient()._from_yahoo("BBAS3")
    assert asset.eventos_encontrados == 2
    assert sum(asset.dividendos_historicos.values()) == 1
    assert any("valor inválido" in warning for warning in asset.avisos)
