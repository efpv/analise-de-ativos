import pytest

from app.services.cash_yield_service import catalog_tickers as app_catalog_tickers
from app.services.ticker_service import TickerService
from src.transformers.catalog import catalog_tickers
from src.transformers.proventos import (
    classify,
    make_event_id,
    normalize_events,
    parse_brl_number,
    parse_date,
)
from src.transformers.quotes import group_by_year, merge_pregoes, normalize_quotes
from src.transformers.ticker import normalize_ticker
from datetime import date, datetime


def test_normalize_ticker():
    assert normalize_ticker(" itub4 ") == "ITUB4"
    assert normalize_ticker("bbas3f") == "BBAS3F"


def test_normalize_ticker_invalido_mesma_mensagem_do_app():
    service = TickerService()
    for value in ("PETR", "ITUB4. SA", ""):
        with pytest.raises(ValueError) as pipeline_error:
            normalize_ticker(value)
        with pytest.raises(ValueError) as app_error:
            service.validate(value)
        assert str(pipeline_error.value) == str(app_error.value)


def test_paridade_de_regex():
    service = TickerService()
    valores = ["BBAS3", "bbas3", "A1LK34", "03BK11", "PETR4F", "PETR", "ABCD1", "ABCD123"]
    for value in valores:
        try:
            esperado = service.validate(value)
        except ValueError:
            esperado = None
        if esperado is None:
            with pytest.raises(ValueError):
                normalize_ticker(value)
        else:
            assert normalize_ticker(value) == esperado


def test_catalogo_tem_376_e_paridade_com_app():
    assert len(catalog_tickers()) == 376
    assert list(catalog_tickers()) == app_catalog_tickers()


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("2024-01-02", "2024-01-02"), ("02/01/2024", "2024-01-02"), ("20240102", "2024-01-02")],
)
def test_parse_date(entrada, esperado):
    assert parse_date(entrada) == esperado


def test_parse_date_invalida():
    with pytest.raises(ValueError):
        parse_date("31/02/2024")


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("R$ 1.234,56", 1234.56),
        ("1,5", 1.5),
        ("1.234", 1234.0),
        ("0.45", 0.45),
        (0.45, 0.45),
    ],
)
def test_parse_brl_number(entrada, esperado):
    assert parse_brl_number(entrada) == esperado


@pytest.mark.parametrize("entrada", ["nan", "inf", "texto", "-1"])
def test_parse_brl_number_invalido(entrada):
    with pytest.raises(ValueError):
        parse_brl_number(entrada)


def test_classify():
    assert classify("JCP") == "JCP"
    assert classify("Juros sobre capital próprio") == "JCP"
    assert classify("Dividendo") == "DIVIDENDO"
    assert classify("Rendimento") == "RENDIMENTO"
    assert classify("Bonificação") == "OUTRO"


def test_make_event_id_deterministico():
    assert (
        make_event_id("ITUB4", "DIVIDENDO", "2024-05-20", 0.45)
        == "ITUB4_DIVIDENDO_2024-05-20_0.450000"
    )
    assert make_event_id("ITUB4", "DIVIDENDO", "2024-05-20", 0.4500000) == (
        make_event_id("ITUB4", "DIVIDENDO", "2024-05-20", "0.450")
    )


def test_make_event_id_sanitiza_caracteres():
    evento_id = make_event_id("ITUB4", "TIPO/Ç", "2024-05-20", 0.45)
    assert "/" not in evento_id
    assert "Ç" not in evento_id


def test_normalize_quotes_dedupe_ordena_e_fallback():
    rows = [
        {"data": "2024-01-03", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
        {"data": "2024-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.0, "volume": 5},
        {"data": "2024-01-03", "open": 1, "high": 2, "low": 0.5, "close": 1.7, "volume": 7},
        {"data": "2024-01-04", "open": 1, "high": 2, "low": 0.5, "close": None},
    ]
    quotes = normalize_quotes(rows)
    assert [quote["data"] for quote in quotes] == ["2024-01-02", "2024-01-03"]
    assert quotes[-1]["close"] == 1.7
    assert quotes[-1]["adj_close"] == 1.7
    assert quotes[-1]["volume"] == 7


def test_merge_pregoes_novo_vence_e_preserva_antigos():
    antigos = [
        {"data": "2024-01-02", "close": 1.0},
        {"data": "2024-01-03", "close": 2.0},
    ]
    novos = [{"data": "2024-01-03", "close": 2.5}, {"data": "2024-01-04", "close": 3.0}]
    merged = merge_pregoes(antigos, novos)
    assert [item["data"] for item in merged] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert merged[1]["close"] == 2.5


def test_normalize_events_dedupe_e_ordena():
    rows = [
        {"tipo": "Dividendo", "data_com": "2024-05-20", "valor": "0,45", "data_ex": "2024-05-17"},
        {"tipo": "Dividendo", "data_com": "2024-05-20", "valor": "0,45", "data_ex": "2024-05-17"},
        {"tipo": "JCP", "data_com": "2024-01-10", "valor": 1.0},
    ]
    eventos = normalize_events(rows, "itub4")
    assert len(eventos) == 2
    assert eventos[0]["tipo_provento"] == "JCP"
    assert eventos[1]["evento_id"] == "ITUB4_DIVIDENDO_2024-05-20_0.450000"
    assert eventos[1]["fonte"] == "B3"


def test_parse_date_aceita_date_datetime_none_e_vazio():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date(date(2024, 1, 2)) == "2024-01-02"
    assert parse_date(datetime(2024, 1, 2, 15, 30)) == "2024-01-02"


def test_parse_brl_number_casos_de_borda():
    assert parse_brl_number(None) is None
    assert parse_brl_number("") is None
    assert parse_brl_number("R$ 1.234,56") == 1234.56
    with pytest.raises(ValueError):
        parse_brl_number("(1,00)")
    with pytest.raises(ValueError):
        parse_brl_number(True)


def test_classify_sem_tipo_retorna_outro():
    assert classify(None) == "OUTRO"
    assert classify("") == "OUTRO"


def test_group_by_year_preserva_ordem():
    quotes = [
        {"data": "2024-01-02", "close": 1.0},
        {"data": "2023-12-28", "close": 2.0},
        {"data": "2024-01-03", "close": 3.0},
    ]
    grouped = group_by_year(quotes)
    assert list(grouped) == [2024, 2023]
    assert [item["data"] for item in grouped[2024]] == ["2024-01-02", "2024-01-03"]


def test_normalize_quotes_descarta_linha_invalida_e_zera_volume():
    rows = [
        {"data": "2024-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.0, "volume": -10},
        {"data": "2024-01-03", "open": None, "high": 2, "low": 0.5, "close": 1.0, "volume": 5},
        {"data": "2024-01-04", "open": 1, "high": 2, "low": 0.5, "close": 1.0, "volume": "nan"},
    ]
    quotes = normalize_quotes(rows)
    assert [quote["data"] for quote in quotes] == ["2024-01-02", "2024-01-04"]
    assert quotes[0]["volume"] == 0
    assert quotes[1]["volume"] == 0


def test_normalize_events_descarta_sem_data_e_sem_valor(caplog):
    rows = [
        {"tipo": "DIVIDENDO", "valor": 1.0},
        {"tipo": "DIVIDENDO", "data_com": "2024-01-10", "valor": 0},
        {"tipo": "DIVIDENDO", "data_com": "2024-01-11", "valor": 2.0},
    ]
    eventos = normalize_events(rows, "ITUB4")
    assert len(eventos) == 1
    assert "provento_sem_data_com" in caplog.text
    assert "provento_sem_valor" in caplog.text

