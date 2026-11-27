import pytest

from app.tests.market_fakes import FakeFirestoreClient
from src.config import load_settings
from src.repositories.market_repository import get_cotacoes, get_proventos


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


def _evento(evento_id, data_com, ticker="ITUB4"):
    return {
        "evento_id": evento_id,
        "ticker": ticker,
        "tipo_provento": "DIVIDENDO",
        "data_com": data_com,
        "data_ex": data_com,
        "data_pagamento": None,
        "valor_bruto": 0.45,
        "fonte": "B3",
    }


def _settings():
    return load_settings(env={}, resolve_adc_project=False)


def _client():
    return FakeFirestoreClient(
        {
            "ativos/ITUB4/cotacoes_anuais/2023": {
                "pregoes": [_quote("2023-12-28", 8.0)]
            },
            "ativos/ITUB4/cotacoes_anuais/2024": {
                "pregoes": [
                    _quote("2024-12-30", 12.0),
                    _quote("2024-01-02", 10.0),
                    _quote("2024-06-10", 11.0),
                ]
            },
            "proventos/B": _evento("B", "2024-05-20"),
            "proventos/A": _evento("A", "2023-01-10"),
            "proventos/C": _evento("C", "2024-06-10", ticker="BBAS3"),
        }
    )


def test_get_cotacoes_intervalo_inclusivo_e_ordenado():
    cotacoes = get_cotacoes(
        "ITUB4", "2024-01-01", "2024-12-31", client=_client(), settings=_settings()
    )
    assert [item["data"] for item in cotacoes] == [
        "2024-01-02",
        "2024-06-10",
        "2024-12-30",
    ]


def test_get_cotacoes_ano_inexistente_e_ignorado():
    cotacoes = get_cotacoes(
        "ITUB4", "2020-01-01", "2021-12-31", client=_client(), settings=_settings()
    )
    assert cotacoes == []


def test_get_proventos_por_ticker_e_ordenado():
    proventos = get_proventos("ITUB4", client=_client(), settings=_settings())
    assert [item["evento_id"] for item in proventos] == ["A", "B"]


def test_get_proventos_com_start_date():
    proventos = get_proventos(
        "ITUB4", "2024-01-01", client=_client(), settings=_settings()
    )
    assert [item["evento_id"] for item in proventos] == ["B"]


def test_get_proventos_fallback_sem_indice():
    client = _client()
    client.fail_query_paths.add("proventos")
    proventos = get_proventos(
        "ITUB4", "2024-01-01", client=client, settings=_settings()
    )
    assert [item["evento_id"] for item in proventos] == ["B"]


def test_get_cotacoes_valida_ticker_e_datas():
    with pytest.raises(ValueError):
        get_cotacoes("PETR", "2024-01-01", "2024-12-31", client=_client(), settings=_settings())
    with pytest.raises(ValueError):
        get_cotacoes("ITUB4", "31/02/2024", "2024-12-31", client=_client(), settings=_settings())
    with pytest.raises(ValueError, match="A data inicial não pode ser posterior"):
        get_cotacoes("ITUB4", "2024-12-31", "2024-01-01", client=_client(), settings=_settings())


def test_get_proventos_valida_ticker_e_data():
    with pytest.raises(ValueError):
        get_proventos("PETR", client=_client(), settings=_settings())
    with pytest.raises(ValueError):
        get_proventos("ITUB4", "31/02/2024", client=_client(), settings=_settings())


def test_get_proventos_usa_id_do_documento_quando_ausente():
    evento = _evento("A", "2024-05-20")
    evento.pop("evento_id")
    client = FakeFirestoreClient({"proventos/A": evento})
    proventos = get_proventos("ITUB4", client=client, settings=_settings())
    assert proventos[0]["evento_id"] == "A"


def test_get_proventos_fallback_sem_start_date():
    client = _client()
    client.fail_query_paths.add("proventos")
    proventos = get_proventos("ITUB4", client=client, settings=_settings())
    assert [item["evento_id"] for item in proventos] == ["A", "B"]

