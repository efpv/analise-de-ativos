import logging

import httpx
import pandas as pd
import pytest

from src.extractors import b3_cotahist, b3_events, yahoo_dividends, yfinance_quotes


def _cotahist_line(ticker, data, open_, high, low, close, volume):
    line = list(" " * 245)
    line[0:2] = list("01")
    line[2:10] = list(data)
    line[12:24] = list(ticker.ljust(12))
    line[56:63] = list(f"{int(open_ * 100):07d}")
    line[63:70] = list(f"{int(high * 100):07d}")
    line[70:77] = list(f"{int(low * 100):07d}")
    line[84:91] = list(f"{int(close * 100):07d}")
    line[115:128] = list(f"{int(volume):013d}")
    return "".join(line) + "\n"


def test_yfinance_extrai_e_renomeia_colunas(monkeypatch):
    frame = pd.DataFrame(
        {
            "Open": [35.0],
            "High": [35.5],
            "Low": [34.9],
            "Close": [35.2],
            "Adj Close": [34.8],
            "Volume": [12345678],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )
    captured = {}

    class FakeTicker:
        def __init__(self, symbol):
            captured["symbol"] = symbol

        def history(self, **kwargs):
            captured.update(kwargs)
            return frame

    monkeypatch.setattr(yfinance_quotes.yf, "Ticker", FakeTicker)
    quotes = yfinance_quotes.extract("itub4", "2024-01-01", "2024-01-03")

    assert captured["symbol"] == "ITUB4.SA"
    assert captured["auto_adjust"] is False
    assert captured["actions"] is False
    assert captured["threads"] is False
    assert captured["end"] == "2024-01-03"
    assert quotes == [
        {
            "data": "2024-01-02",
            "open": 35.0,
            "high": 35.5,
            "low": 34.9,
            "close": 35.2,
            "adj_close": 34.8,
            "volume": 12345678,
        }
    ]


def test_yfinance_vazio_devolve_lista(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            return pd.DataFrame()

    monkeypatch.setattr(yfinance_quotes.yf, "Ticker", FakeTicker)
    assert yfinance_quotes.extract("ITUB4", "2024-01-01", "2024-01-03") == []


def test_yfinance_remove_parametros_nao_suportados(monkeypatch):
    frame = pd.DataFrame(
        {
            "Open": [35.0],
            "High": [35.5],
            "Low": [34.9],
            "Close": [35.2],
            "Adj Close": [35.2],
            "Volume": [100],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )
    capturados = []

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            capturados.append(dict(kwargs))
            if "progress" in kwargs or "threads" in kwargs:
                raise TypeError(
                    "PriceHistory.history() got an unexpected keyword argument 'progress'"
                )
            return frame

    monkeypatch.setattr(yfinance_quotes.yf, "Ticker", FakeTicker)
    quotes = yfinance_quotes.extract("ITUB4", "2024-01-01", "2024-01-03")

    assert quotes[0]["close"] == 35.2
    assert len(capturados) == 2
    assert "progress" not in capturados[1]
    assert "threads" not in capturados[1]
    assert capturados[1]["auto_adjust"] is False
    assert capturados[1]["actions"] is False



def test_cotahist_le_precos_e_volume(tmp_path, caplog):
    (tmp_path / "COTAHIST_A2024.TXT").write_text(
        _cotahist_line("ITUB4", "20240102", 35.1, 35.5, 34.9, 35.2, 12345678),
        encoding="latin-1",
    )
    with caplog.at_level(logging.WARNING):
        quotes = b3_cotahist.extract("ITUB4", 2024, tmp_path)
    assert quotes[0]["close"] == 35.2
    assert quotes[0]["adj_close"] == 35.2
    assert quotes[0]["volume"] == 12345678
    assert "adj_close_igual_close" in caplog.text


def test_cotahist_arquivo_ausente(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert b3_cotahist.extract("ITUB4", 2024, tmp_path) == []
    assert "cotahist_ausente" in caplog.text


def test_b3_events_mapeia_payload():
    payload = {
        "results": [
            {
                "ticker": "ITUB4",
                "tipoEvento": "DIVIDENDO",
                "dataCom": "20/05/2024",
                "dataEx": "17/05/2024",
                "dataPagamento": "24/05/2024",
                "valor": "0,45",
            },
            {
                "ticker": "ITUB4",
                "tipoEvento": "DIVIDENDO",
                "dataCom": "20/05/2025",
                "valor": "0,50",
            },
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        eventos = b3_events.extract(
            "ITUB4", "2024-01-01", "2024-12-31", url="https://b3.test/events", client=client
        )
    assert len(eventos) == 1
    assert eventos[0]["evento_id"] == "ITUB4_DIVIDENDO_2024-05-20_0.450000"
    assert eventos[0]["data_ex"] == "2024-05-17"
    assert eventos[0]["fonte"] == "B3"


def test_b3_events_500_gera_erro():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(b3_events.B3EventsError):
            b3_events.extract(
                "ITUB4",
                "2024-01-01",
                "2024-12-31",
                url="https://b3.test/events",
                client=client,
                max_retries=1,
            )


def test_b3_events_timeout_gera_erro():
    def handler(request):
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(b3_events.B3EventsError):
            b3_events.extract(
                "ITUB4",
                "2024-01-01",
                "2024-12-31",
                url="https://b3.test/events",
                client=client,
                max_retries=1,
            )


def test_b3_events_sem_url_nao_faz_requisicao():
    def handler(request):
        raise AssertionError("Não deve haver requisição")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        assert b3_events.extract(
            "ITUB4", "2024-01-01", "2024-12-31", url="", client=client
        ) == []


def test_yahoo_dividends_usa_data_ex_como_data_com(monkeypatch):
    series = pd.Series(
        [0.5, 0.25],
        index=pd.to_datetime(["2024-05-20", "2025-01-10"]),
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.dividends = series

    monkeypatch.setattr(yahoo_dividends.yf, "Ticker", FakeTicker)
    eventos = yahoo_dividends.extract("ITUB4", "2024-01-01", "2024-12-31")

    assert len(eventos) == 1
    assert eventos[0]["data_com"] == "2024-05-20"
    assert eventos[0]["data_ex"] == "2024-05-20"
    assert eventos[0]["data_pagamento"] is None
    assert eventos[0]["tipo_provento"] == "OUTRO"
    assert eventos[0]["fonte"] == yahoo_dividends.FONTE


def test_yahoo_dividends_vazio_devolve_lista(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            self.dividends = pd.Series(dtype="float64")

    monkeypatch.setattr(yahoo_dividends.yf, "Ticker", FakeTicker)
    assert yahoo_dividends.extract("ITUB4", "2024-01-01", "2024-12-31") == []


def test_yfinance_sem_adj_close_usa_close(monkeypatch):
    frame = pd.DataFrame(
        {
            "Open": [35.0],
            "High": [35.5],
            "Low": [34.9],
            "Close": [35.2],
            "Volume": [100],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            return frame

    monkeypatch.setattr(yfinance_quotes.yf, "Ticker", FakeTicker)
    quotes = yfinance_quotes.extract("ITUB4", "2024-01-01", "2024-01-03")
    assert quotes[0]["adj_close"] == 35.2


def test_yfinance_descarta_linha_com_close_nan(monkeypatch):
    frame = pd.DataFrame(
        {
            "Open": [35.0, 36.0],
            "High": [35.5, 36.5],
            "Low": [34.9, 35.9],
            "Close": [float("nan"), 36.2],
            "Adj Close": [float("nan"), 36.2],
            "Volume": [100, 200],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            return frame

    monkeypatch.setattr(yfinance_quotes.yf, "Ticker", FakeTicker)
    quotes = yfinance_quotes.extract("ITUB4", "2024-01-01", "2024-01-04")
    assert [quote["data"] for quote in quotes] == ["2024-01-03"]


def test_cotahist_ignora_linhas_invalidas(tmp_path):
    valid = _cotahist_line("ITUB4", "20240102", 35.1, 35.5, 34.9, 35.2, 12345678)
    invalid_price = list(valid)
    invalid_price[56:63] = list("xxxxxxx")
    content = (
        "01\n"
        + valid
        + "".join(invalid_price)
        + _cotahist_line("BBAS3", "20240103", 10.0, 10.5, 9.9, 10.2, 500)
    )
    (tmp_path / "COTAHIST_A2024.TXT").write_text(content, encoding="latin-1")
    quotes = b3_cotahist.extract("ITUB4", 2024, tmp_path)
    assert [quote["data"] for quote in quotes] == ["2024-01-02"]


def test_b3_events_aceita_lista_e_aliases():
    payload = [
        {
            "codigo": "ITUB4",
            "tipo_provento": "JCP",
            "data_com": "2024-05-20",
            "data_ex": "2024-05-17",
            "data_pagamento": "2024-05-24",
            "valorBruto": "1,25",
            "fonte": "B3",
        }
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        eventos = b3_events.extract(
            "ITUB4", "2024-01-01", "2024-12-31", url="https://b3.test/events", client=client
        )
    assert eventos[0]["tipo_provento"] == "JCP"
    assert eventos[0]["valor_bruto"] == 1.25
    assert eventos[0]["evento_id"] == "ITUB4_JCP_2024-05-20_1.250000"


def test_b3_events_4xx_nao_repete():
    chamadas = []

    def handler(request):
        chamadas.append(request)
        return httpx.Response(400)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(b3_events.B3EventsError):
            b3_events.extract(
                "ITUB4",
                "2024-01-01",
                "2024-12-31",
                url="https://b3.test/events",
                client=client,
                max_retries=3,
            )
    assert len(chamadas) == 1


def test_b3_events_json_invalido_gera_erro():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="nao-e-json")
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(b3_events.B3EventsError):
            b3_events.extract(
                "ITUB4", "2024-01-01", "2024-12-31", url="https://b3.test/events", client=client
            )


def test_b3_events_data_invalida_e_ignorada(caplog):
    payload = {
        "data": [
            {"ticker": "ITUB4", "tipo": "DIVIDENDO", "dataCom": "31/02/2024", "valor": 1},
            {
                "ticker": "ITUB4",
                "tipo": "DIVIDENDO",
                "dataCom": "20/05/2024",
                "valor": 0.45,
            },
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        eventos = b3_events.extract(
            "ITUB4", "2024-01-01", "2024-12-31", url="https://b3.test/events", client=client
        )
    assert len(eventos) == 1
    assert "provento_data_invalida" in caplog.text


def test_b3_events_valor_invalido_gera_erro():
    payload = [
        {
            "ticker": "ITUB4",
            "tipo": "DIVIDENDO",
            "dataCom": "20/05/2024",
            "valor": "abc",
        }
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(b3_events.B3EventsError):
            b3_events.extract(
                "ITUB4", "2024-01-01", "2024-12-31", url="https://b3.test/events", client=client
            )


def test_b3_events_nao_loga_url_ou_corpo(caplog):
    def handler(request):
        return httpx.Response(400, text="corpo-secreto")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(b3_events.B3EventsError):
            b3_events.extract(
                "ITUB4",
                "2024-01-01",
                "2024-12-31",
                url="https://b3.test/events?token=segredo",
                client=client,
            )

    assert "segredo" not in caplog.text
    assert "corpo-secreto" not in caplog.text


def test_b3_events_parser_rejeita_payload_sem_lista():
    parser = b3_events.B3EventsPayloadParser()
    with pytest.raises(b3_events.B3EventsError):
        parser.parse({"foo": "bar"}, "ITUB4", "2024-01-01", "2024-12-31")
    with pytest.raises(b3_events.B3EventsError):
        parser.parse("texto", "ITUB4", "2024-01-01", "2024-12-31")


def test_b3_events_parser_ignora_item_que_nao_e_objeto():
    payload = [
        123,
        {"ticker": "ITUB4", "tipo": "DIVIDENDO", "dataCom": "20/05/2024", "valor": 0.45},
    ]
    rows = b3_events.B3EventsPayloadParser().parse(
        payload, "ITUB4", "2024-01-01", "2024-12-31"
    )
    assert len(rows) == 1
    assert rows[0]["data_com"] == "2024-05-20"



