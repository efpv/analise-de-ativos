from datetime import date

from app.tests.market_fakes import FakeFirestoreClient
from src.config import load_settings
from src.extractors.b3_events import B3EventsError
from src.pipelines import market_pipeline
from src.pipelines.market_pipeline import run
from src.utils.dates import full_window, incremental_window


def _settings(**env):
    base = {"MARKET_TICKERS": "ITUB4", "MARKET_WORKERS": "1"}
    base.update(env)
    return load_settings(env=base, resolve_adc_project=False)


def _quote(data, close=10.0):
    return {
        "data": data,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "adj_close": close,
        "volume": 100,
    }


def _evento(data_com="2024-05-20", data_pagamento=None):
    return {
        "evento_id": f"ITUB4_DIVIDENDO_{data_com}_0.450000",
        "ticker": "ITUB4",
        "tipo_provento": "DIVIDENDO",
        "data_com": data_com,
        "data_ex": data_com,
        "data_pagamento": data_pagamento,
        "valor_bruto": 0.45,
        "fonte": "B3",
    }


def test_janela_full_cinco_anos():
    assert full_window(date(2026, 11, 26), 5) == (date(2021, 11, 26), date(2026, 11, 26))


def test_janela_full_29_de_fevereiro():
    assert full_window(date(2024, 2, 29), 1) == (date(2023, 2, 28), date(2024, 2, 29))


def test_janela_incremental_sessenta_dias():
    assert incremental_window(date(2026, 11, 26), 60) == (
        date(2026, 9, 27),
        date(2026, 11, 26),
    )


def test_incremental_preserva_pregoes_antigos(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2026, 11, 26))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes,
        "extract",
        lambda *args, **kwargs: [_quote("2026-11-25", 11.0)],
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends, "extract", lambda *args, **kwargs: []
    )

    client = FakeFirestoreClient(
        {
            "ativos/ITUB4": {
                "ticker": "ITUB4",
                "quantidade_cotacoes": 1,
                "inicio_serie": "2026-01-02",
                "fim_serie": "2026-01-02",
            },
            "ativos/ITUB4/cotacoes_anuais/2026": {
                "pregoes": [_quote("2026-01-02", 9.0)]
            },
        }
    )
    resultados = run(
        modo="incremental",
        tickers=("ITUB4",),
        settings=_settings(),
        client=client,
    )

    assert resultados[0].erros == ()
    pregoes = client.data["ativos/ITUB4/cotacoes_anuais/2026"]["pregoes"]
    assert [item["data"] for item in pregoes] == ["2026-01-02", "2026-11-25"]
    metadata = client.data["ativos/ITUB4"]
    assert metadata["quantidade_cotacoes"] == 2
    assert metadata["inicio_serie"] == "2026-01-02"
    assert metadata["fim_serie"] == "2026-11-25"


def test_metadados_min_max_e_ultimo_provento(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes,
        "extract",
        lambda *args, **kwargs: [_quote("2024-06-10", 20.0)],
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends,
        "extract",
        lambda *args, **kwargs: [_evento("2024-05-20", "2024-05-24")],
    )

    client = FakeFirestoreClient()
    run(modo="full", tickers=("ITUB4",), settings=_settings(), client=client)

    metadata = client.data["ativos/ITUB4"]
    assert metadata["inicio_serie"] == "2024-06-10"
    assert metadata["fim_serie"] == "2024-06-10"
    assert metadata["ultimo_provento_em"] == "2024-05-24"
    assert metadata["quantidade_proventos"] == 1


def test_falha_em_um_ticker_nao_derruba_o_lote(monkeypatch):
    def fake_extract(ticker, *args, **kwargs):
        if ticker == "BBAS3":
            raise RuntimeError("falha simulada")
        return [_quote("2024-06-10")]

    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(market_pipeline.yfinance_quotes, "extract", fake_extract)
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends, "extract", lambda *args, **kwargs: []
    )

    resultados = run(
        modo="full",
        tickers=("ITUB4", "BBAS3"),
        settings=_settings(),
        client=FakeFirestoreClient(),
    )

    assert [result.ticker for result in resultados] == ["ITUB4", "BBAS3"]
    assert resultados[0].erros == ()
    assert resultados[1].erros


def test_dry_run_nao_cria_cliente_nem_escreve(monkeypatch):
    def unexpected_client(settings):
        raise AssertionError("dry-run não deve criar cliente")

    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(market_pipeline, "get_client", unexpected_client)
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes,
        "extract",
        lambda *args, **kwargs: [_quote("2024-06-10")],
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends,
        "extract",
        lambda *args, **kwargs: [_evento()],
    )

    resultados = run(
        modo="full",
        tickers=("ITUB4",),
        settings=_settings(),
        dry_run=True,
    )
    assert resultados[0].cotacoes == 1
    assert resultados[0].proventos == 1
    assert resultados[0].erros == ()


def test_sem_cotacoes_nao_sobrescreve_pregoes(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes, "extract", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends, "extract", lambda *args, **kwargs: []
    )

    client = FakeFirestoreClient(
        {
            "ativos/ITUB4": {"ticker": "ITUB4", "quantidade_cotacoes": 1},
            "ativos/ITUB4/cotacoes_anuais/2024": {"pregoes": [_quote("2024-01-02")]},
        }
    )
    run(modo="full", tickers=("ITUB4",), settings=_settings(), client=client)

    assert client.write_count == 0
    assert client.data["ativos/ITUB4/cotacoes_anuais/2024"]["pregoes"] == [
        _quote("2024-01-02")
    ]


def test_fallback_b3_para_yahoo(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes, "extract", lambda *args, **kwargs: []
    )

    def falha_b3(*args, **kwargs):
        raise B3EventsError("indisponível")

    evento_yahoo = _evento()
    evento_yahoo["fonte"] = "Yahoo Finance (data ex como data_com)"
    monkeypatch.setattr(market_pipeline.b3_events, "extract", falha_b3)
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends,
        "extract",
        lambda *args, **kwargs: [evento_yahoo],
    )

    client = FakeFirestoreClient()
    run(
        modo="full",
        tickers=("ITUB4",),
        settings=_settings(MARKET_B3_EVENTS_URL="https://b3.test/events"),
        client=client,
    )

    evento = client.data["proventos/ITUB4_DIVIDENDO_2024-05-20_0.450000"]
    assert evento["fonte"].startswith("Yahoo")


def test_cotahist_tem_precedencia_sobre_yfinance(monkeypatch, tmp_path):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes,
        "extract",
        lambda *args, **kwargs: [_quote("2024-06-10", 10.0)],
    )
    monkeypatch.setattr(
        market_pipeline.b3_cotahist,
        "extract",
        lambda *args, **kwargs: [_quote("2024-06-10", 99.0)],
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends, "extract", lambda *args, **kwargs: []
    )

    client = FakeFirestoreClient()
    run(
        modo="full",
        tickers=("ITUB4",),
        settings=_settings(MARKET_B3_COTAHIST_DIR=str(tmp_path)),
        client=client,
    )

    pregoes = client.data["ativos/ITUB4/cotacoes_anuais/2024"]["pregoes"]
    assert len(pregoes) == 1
    assert pregoes[0]["close"] == 99.0


def test_apenas_proventos_atualiza_metadados(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes, "extract", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends,
        "extract",
        lambda *args, **kwargs: [_evento("2024-05-20", "2024-05-24")],
    )

    client = FakeFirestoreClient(
        {
            "ativos/ITUB4": {
                "ticker": "ITUB4",
                "quantidade_cotacoes": 3,
                "inicio_serie": "2024-01-02",
                "fim_serie": "2024-06-10",
            }
        }
    )
    resultados = run(modo="full", tickers=("ITUB4",), settings=_settings(), client=client)

    assert resultados[0].erros == ()
    metadata = client.data["ativos/ITUB4"]
    assert metadata["inicio_serie"] == "2024-01-02"
    assert metadata["fim_serie"] == "2024-06-10"
    assert metadata["ultimo_provento_em"] == "2024-05-24"
    assert metadata["quantidade_cotacoes"] == 3
    assert metadata["quantidade_proventos"] == 1


def test_b3_com_sucesso_nao_usa_yahoo(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes, "extract", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        market_pipeline.b3_events, "extract", lambda *args, **kwargs: [_evento()]
    )

    def nao_deve_chamar(*args, **kwargs):
        raise AssertionError("Yahoo não deve ser usado quando a B3 responde")

    monkeypatch.setattr(market_pipeline.yahoo_dividends, "extract", nao_deve_chamar)

    client = FakeFirestoreClient()
    run(
        modo="full",
        tickers=("ITUB4",),
        settings=_settings(MARKET_B3_EVENTS_URL="https://b3.test/events"),
        client=client,
    )

    assert "proventos/ITUB4_DIVIDENDO_2024-05-20_0.450000" in client.data


def test_novo_ano_soma_ao_contador_de_cotacoes(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2025, 1, 10))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes,
        "extract",
        lambda *args, **kwargs: [_quote("2025-01-02", 11.0)],
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends, "extract", lambda *args, **kwargs: []
    )

    client = FakeFirestoreClient(
        {
            "ativos/ITUB4": {
                "ticker": "ITUB4",
                "quantidade_cotacoes": 1,
                "inicio_serie": "2024-12-30",
                "fim_serie": "2024-12-30",
            },
            "ativos/ITUB4/cotacoes_anuais/2024": {
                "pregoes": [_quote("2024-12-30", 10.0)]
            },
        }
    )
    run(modo="full", tickers=("ITUB4",), settings=_settings(), client=client)

    assert client.data["ativos/ITUB4"]["quantidade_cotacoes"] == 2
    assert client.data["ativos/ITUB4/cotacoes_anuais/2025"]["pregoes"] == [
        _quote("2025-01-02", 11.0)
    ]
    assert client.data["ativos/ITUB4/cotacoes_anuais/2024"]["pregoes"] == [
        _quote("2024-12-30", 10.0)
    ]


def test_run_cria_cliente_quando_nao_e_dry_run(monkeypatch):
    monkeypatch.setattr(market_pipeline, "today_b3", lambda: date(2024, 12, 31))
    monkeypatch.setattr(
        market_pipeline.yfinance_quotes,
        "extract",
        lambda *args, **kwargs: [_quote("2024-06-10", 10.0)],
    )
    monkeypatch.setattr(
        market_pipeline.yahoo_dividends, "extract", lambda *args, **kwargs: []
    )

    client = FakeFirestoreClient()
    chamadas = []

    def fake_get_client(settings):
        chamadas.append(settings)
        return client

    monkeypatch.setattr(market_pipeline, "get_client", fake_get_client)
    resultados = run(modo="full", tickers=("ITUB4",), settings=_settings())

    assert resultados[0].erros == ()
    assert len(chamadas) == 1
    assert "ativos/ITUB4" in client.data


