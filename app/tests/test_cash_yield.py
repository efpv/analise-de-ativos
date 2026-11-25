from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.models.valuation import AssetData
from app.repositories.asset_cache_repository import AssetCacheRepository
from app.services.cash_yield_service import CashYieldService, evaluate, rank

TODAY = date(2026, 6, 1)


def asset(ticker="AAAA3", price=10.0, dividends=None):
    return AssetData(
        ticker=ticker, empresa=f"Empresa {ticker}", preco_atual=price, dividend_yield=None,
        dividendos_historicos=dividends if dividends is not None else {2023: 0.7, 2024: 0.8, 2025: 0.9},
        fonte="Teste",
    )


def test_aprova_quando_y1_dos_tres_anos_e_pelo_menos_6():
    candidate = evaluate(asset(), TODAY)
    assert candidate.y1 == pytest.approx(9.0)
    assert candidate.y1_minimo == pytest.approx(7.0)
    assert [item.ano for item in candidate.anos] == [2023, 2024, 2025]


def test_aceita_y1_exatamente_igual_a_6():
    assert evaluate(asset(dividends={2023: 0.6, 2024: 0.6, 2025: 0.6}), TODAY) is not None


@pytest.mark.parametrize("dividends", [
    {2023: 0.7, 2024: 0.8, 2025: 0.5},
    {2023: 0.5, 2024: 0.8, 2025: 0.9},
    {2024: 0.8, 2025: 0.9},
    {2023: 0.0, 2024: 0.8, 2025: 0.9},
    {2023: 0.7, 2024: 0.8, 2025: 0.0},
])
def test_reprova_sem_regularidade_ou_y1_abaixo_de_6(dividends):
    assert evaluate(asset(dividends=dividends), TODAY) is None


def test_ano_corrente_parcial_e_ignorado():
    assert evaluate(asset(dividends={2023: 0.7, 2024: 0.8, 2025: 0.9, 2026: 0.0}), TODAY) is not None


def test_ordena_por_consistencia_e_depois_y1():
    a = evaluate(asset("AAAA3", dividends={2023: 0.9, 2024: 0.9, 2025: 3.0}), TODAY)
    b = evaluate(asset("BBBB3", dividends={2023: 0.8, 2024: 0.8, 2025: 0.8}), TODAY)
    c = evaluate(asset("CCCC3", dividends={2023: 0.8, 2024: 0.8, 2025: 1.2}), TODAY)
    assert [item.ticker for item in rank([b, a, c])] == ["AAAA3", "CCCC3", "BBBB3"]


class FakeTickerService:
    def __init__(self, assets):
        self.assets = assets
        self.asset_calls = []
        self.price_calls = []

    def get_asset(self, ticker):
        self.asset_calls.append(ticker)
        if ticker == "FALHA3":
            raise LookupError("Ativo não encontrado.")
        return self.assets[ticker]

    def get_price(self, ticker):
        self.price_calls.append(ticker)
        return self.assets[ticker].preco_atual * 2


def qualifying(ticker, price=10.0):
    year = date.today().year
    return asset(ticker, price, {year - 3: 0.7, year - 2: 0.8, year - 1: 0.9})


def make_service(assets, tmp_path):
    return CashYieldService(
        FakeTickerService(assets), str(tmp_path / "cache.json"),
        AssetCacheRepository(str(tmp_path / "assets.sqlite")),
    )


def test_servico_filtra_ordena_e_persiste_cache(tmp_path):
    cache = tmp_path / "cache.json"
    assets = {"AAAA3": qualifying("AAAA3"), "BBBB3": qualifying("BBBB3", 5.0), "CCCC3": asset("CCCC3", dividends={})}
    service = make_service(assets, tmp_path)
    assert service.status()[3] is None

    assert service.start(["AAAA3", "BBBB3", "CCCC3", "FALHA3"], wait=True)
    running, processed, total, snapshot = service.status()
    assert not running and processed == total == 4
    assert [item.ticker for item in snapshot.candidatos] == ["BBBB3", "AAAA3"]
    assert snapshot.total_analisados == 3
    assert snapshot.total_qualificados == 2
    assert snapshot.avisos

    reloaded = CashYieldService(FakeTickerService({}), str(cache)).status()[3]
    assert reloaded == snapshot


def test_cache_corrompido_e_ignorado(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("{invalido")
    assert CashYieldService(FakeTickerService({}), str(cache)).status()[3] is None


def test_api_limita_a_30_e_retorna_posicoes(tmp_path, monkeypatch):
    tickers = [f"AB{index:02d}3" for index in range(35)]
    assets = {ticker: qualifying(ticker, 5.0 + index * 0.01) for index, ticker in enumerate(tickers)}
    service = make_service(assets, tmp_path)
    monkeypatch.setattr(routes, "cash_yield_service", service)
    client = TestClient(app)

    assert client.get("/api/v1/cash-yield").json()["status"] == "vazio"
    service.start(tickers, wait=True)
    data = client.get("/api/v1/cash-yield").json()
    assert data["status"] == "pronto"
    assert data["total_qualificados"] == 35
    assert len(data["itens"]) == 30
    assert [item["posicao"] for item in data["itens"]] == list(range(1, 31))
    assert data["itens"][0]["ticker"] == tickers[0]


def test_refresh_inicia_varredura_sem_bloquear(monkeypatch):
    started = []
    service = SimpleNamespace(
        start=lambda: started.append(True), status=lambda: (True, 1, 10, None),
    )
    monkeypatch.setattr(routes, "cash_yield_service", service)
    response = TestClient(app).post("/api/v1/cash-yield/refresh")
    assert response.status_code == 202
    assert started == [True]
    assert response.json()["status"] == "calculando"


def test_pagina_cash_yield():
    response = TestClient(app).get("/cash-yield")
    assert response.status_code == 200
    assert "30 melhores ações" in response.text
    assert "cash-yield-body" in response.text


def age_cache(repository, ticker, dividends_days=0, price_days=0):
    now = datetime.now(timezone.utc)
    with repository._connect() as connection:
        connection.execute(
            "UPDATE asset_cache SET dividendos_em = ?, preco_em = ? WHERE ticker = ?",
            ((now - timedelta(days=dividends_days)).isoformat(), (now - timedelta(days=price_days)).isoformat(), ticker),
        )


def test_dados_recentes_nao_consultam_a_fonte(tmp_path):
    service = make_service({"AAAA3": qualifying("AAAA3")}, tmp_path)
    service.load_asset("AAAA3")
    service.load_asset("AAAA3")
    assert service.ticker_service.asset_calls == ["AAAA3"]
    assert service.ticker_service.price_calls == []


def test_preco_vencido_consulta_somente_o_preco(tmp_path):
    service = make_service({"AAAA3": qualifying("AAAA3")}, tmp_path)
    service.load_asset("AAAA3")
    age_cache(service.asset_cache, "AAAA3", price_days=2)
    refreshed = service.load_asset("AAAA3")
    assert refreshed.preco_atual == pytest.approx(20.0)
    assert service.ticker_service.asset_calls == ["AAAA3"]
    assert service.ticker_service.price_calls == ["AAAA3"]
    assert service.asset_cache.get("AAAA3").asset.preco_atual == pytest.approx(20.0)


def test_dividendos_vencidos_consultam_a_fonte_novamente(tmp_path):
    service = make_service({"AAAA3": qualifying("AAAA3")}, tmp_path)
    service.load_asset("AAAA3")
    age_cache(service.asset_cache, "AAAA3", dividends_days=31)
    service.load_asset("AAAA3")
    assert service.ticker_service.asset_calls == ["AAAA3", "AAAA3"]


def test_ativo_nao_encontrado_fica_salvo_por_um_dia(tmp_path):
    service = make_service({}, tmp_path)
    for _ in range(2):
        with pytest.raises(LookupError):
            service.load_asset("FALHA3")
    assert service.ticker_service.asset_calls == ["FALHA3"]
