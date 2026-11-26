from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.models.valuation import AssetData, Fundamentals
from app.repositories.asset_cache_repository import AssetCacheRepository
from app.repositories.firestore_store import FirestoreAssetCache, FirestoreStateStore
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


HEALTHY = Fundamentals(
    divida_liquida=100.0, ebitda=100.0, liquidez_corrente=1.5, p_vp=1.2, roe=15.0,
    volume_financeiro=20_000_000.0, fluxo_caixa_operacional=80.0, fluxo_caixa_livre=10.0,
)


class FakeTickerService:
    def __init__(self, assets, fundamentals=None):
        self.assets = assets
        self.fundamentals = fundamentals or {}
        self.fundamentals_calls = []
        self.asset_calls = []
        self.price_calls = []

    def get_asset(self, ticker):
        self.asset_calls.append(ticker)
        if ticker == "FALHA3":
            raise LookupError("Ativo não encontrado.")
        return self.assets[ticker]

    def get_fundamentals(self, ticker):
        self.fundamentals_calls.append(ticker)
        return self.fundamentals.get(ticker, HEALTHY)

    def get_price(self, ticker):
        self.price_calls.append(ticker)
        return self.assets[ticker].preco_atual * 2


def qualifying(ticker, price=10.0):
    year = date.today().year
    return asset(ticker, price, {year - 3: 0.7, year - 2: 0.8, year - 1: 0.9})


def make_service(assets, tmp_path, fundamentals=None):
    return CashYieldService(
        FakeTickerService(assets, fundamentals), str(tmp_path / "cache.json"),
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
    assert 'id="cash-yield-refresh"' not in response.text


def test_pagina_atualizacao_cash_yield():
    response = TestClient(app).get("/gerarlista")
    assert response.status_code == 200
    assert "<title>Atualizar Cash-yield" in response.text
    assert 'id="cash-yield-refresh"' in response.text


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


class FakeDocument:
    def __init__(self, store, name):
        self.store, self.name = store, name

    @property
    def exists(self):
        return self.name in self.store

    def get(self):
        return self

    def to_dict(self):
        return self.store.get(self.name)

    def set(self, data):
        self.store[self.name] = dict(data)

    def update(self, data):
        self.store[self.name].update(data)


class FakeFirestore:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        store = self.data.setdefault(name, {})
        return SimpleNamespace(document=lambda doc: FakeDocument(store, doc))


def firestore_service(assets, client):
    return CashYieldService(
        FakeTickerService(assets), asset_cache=FirestoreAssetCache(client), state_store=FirestoreStateStore(client),
    )


def test_firestore_sobrevive_a_nova_instancia():
    client = FakeFirestore()
    first = firestore_service({"AAAA3": qualifying("AAAA3"), "BBBB3": qualifying("BBBB3", 5.0)}, client)
    first.start(["AAAA3", "BBBB3"], wait=True)

    second = firestore_service({}, client)
    running, processed, total, snapshot = second.status()
    assert not running and processed == total == 2
    assert [item.ticker for item in snapshot.candidatos] == ["BBBB3", "AAAA3"]
    assert second.load_asset("AAAA3").preco_atual == pytest.approx(10.0)
    assert second.ticker_service.asset_calls == []


def test_firestore_impede_varredura_simultanea_entre_instancias():
    client = FakeFirestore()
    other = firestore_service({}, client)
    other._save_progress(True, 5, 10)
    service = firestore_service({"AAAA3": qualifying("AAAA3")}, client)
    assert service.status()[:3] == (True, 5, 10)
    assert service.start(["AAAA3"], wait=True) is False


def test_varredura_travada_ha_mais_de_10_minutos_e_ignorada():
    client = FakeFirestore()
    service = firestore_service({"AAAA3": qualifying("AAAA3")}, client)
    service._save_progress(True, 5, 10)
    progress = client.data["cash_yield"]["progress"]
    progress["atualizado_em"] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    assert service.status()[0] is False
    assert service.start(["AAAA3"], wait=True) is True


def status_of(candidate, name):
    return next(item.status for item in candidate.criterios if item.nome == name)


@pytest.mark.parametrize("changes,name,expected", [
    ({"divida_liquida": 450.0}, "Dívida líquida / EBITDA", "reprovado"),
    ({"divida_liquida": 250.0}, "Dívida líquida / EBITDA", "atencao"),
    ({"divida_liquida": -10.0}, "Dívida líquida / EBITDA", "aprovado"),
    ({"divida_liquida": 50.0, "ebitda": 0.0}, "Dívida líquida / EBITDA", "reprovado"),
    ({"volume_financeiro": 500_000.0}, "Liquidez na bolsa", "reprovado"),
    ({"volume_financeiro": 3_000_000.0}, "Liquidez na bolsa", "atencao"),
    ({"fluxo_caixa_operacional": -1.0}, "Geração de caixa", "reprovado"),
    ({"fluxo_caixa_livre": -5.0}, "Geração de caixa", "atencao"),
    ({"roe": -3.0}, "ROE", "reprovado"),
    ({"roe": 30.0, "divida_liquida": 250.0}, "ROE", "atencao"),
    ({"liquidez_corrente": 0.7}, "Liquidez corrente", "atencao"),
])
def test_criterios_de_saude_financeira(changes, name, expected):
    candidate = evaluate(replace(qualifying("AAAA3"), fundamentos=replace(HEALTHY, **changes)))
    assert status_of(candidate, name) == expected


def test_liquidez_corrente_e_pvp_nunca_reprovam():
    candidate = evaluate(replace(qualifying("AAAA3"), fundamentos=replace(HEALTHY, liquidez_corrente=0.1, p_vp=9.0)))
    assert candidate.veredito == "atencao"


def test_sem_indicadores_fica_em_atencao_e_nao_reprova():
    assert evaluate(qualifying("AAAA3")).veredito == "atencao"


def test_alerta_de_dividendo_extraordinario_e_corte():
    year = date.today().year
    spike = asset("AAAA3", 5.0, {year - 3: 0.4, year - 2: 0.4, year - 1: 1.5})
    assert any("extraordinário" in text for text in evaluate(spike).alertas)
    cut = asset("BBBB3", 5.0, {year - 3: 0.8, year - 2: 0.9, year - 1: 0.35})
    assert any("caiu mais de 50%" in text for text in evaluate(cut).alertas)
    assert evaluate(qualifying("CCCC3")).alertas == ()


def test_ranking_prioriza_aprovadas_sobre_atencao():
    approved = evaluate(replace(qualifying("AAAA3", 10.0), fundamentos=HEALTHY))
    attention = evaluate(replace(qualifying("BBBB3", 5.0)))
    assert attention.y1_minimo > approved.y1_minimo
    assert [item.ticker for item in rank([attention, approved])] == ["AAAA3", "BBBB3"]


def test_varredura_exclui_reprovadas_por_balanco_e_busca_indicadores_so_de_quem_passou_no_y1(tmp_path):
    year = date.today().year
    assets = {
        "AAAA3": qualifying("AAAA3"), "BBBB3": qualifying("BBBB3"),
        "CCCC3": asset("CCCC3", dividends={year - 1: 0.1}),
    }
    debt = replace(HEALTHY, divida_liquida=900.0)
    service = make_service(assets, tmp_path, {"BBBB3": debt})
    service.start(["AAAA3", "BBBB3", "CCCC3"], wait=True)
    snapshot = service.status()[3]
    assert [item.ticker for item in snapshot.candidatos] == ["AAAA3"]
    assert snapshot.total_reprovados_fundamentos == 1
    assert any("endividamento" in text for text in snapshot.avisos)
    assert sorted(service.ticker_service.fundamentals_calls) == ["AAAA3", "BBBB3"]

    reloaded = make_service({}, tmp_path).status()[3]
    assert reloaded.candidatos[0].criterios == snapshot.candidatos[0].criterios


def test_indicadores_salvos_nao_sao_consultados_de_novo(tmp_path):
    service = make_service({"AAAA3": qualifying("AAAA3")}, tmp_path)
    service.start(["AAAA3"], wait=True)
    service.start(["AAAA3"], wait=True)
    assert service.ticker_service.fundamentals_calls == ["AAAA3"]


def test_endpoint_de_analise_detalhada(tmp_path, monkeypatch):
    fake = FakeTickerService({"AAAA3": qualifying("AAAA3")}, {"AAAA3": replace(HEALTHY, divida_liquida=450.0)})
    monkeypatch.setattr(routes, "ticker_service", fake)
    monkeypatch.setattr(routes, "cash_yield_service", CashYieldService(fake, str(tmp_path / "c.json")))
    fake.get_asset = lambda ticker: fake.assets[ticker]
    data = TestClient(app).get("/api/v1/cash-yield/AAAA3/analise?taxa=0.06").json()
    assert data["veredito"] == "reprovada"
    assert data["preco_teto"]["preco_teto_media_5anos"] > 0
    assert [c["nome"] for c in data["saude_financeira"]][0] == "Dívida líquida / EBITDA"
    assert data["riscos"] and data["resumo"]
