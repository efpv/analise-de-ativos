import pytest

from app.models.valuation import AssetData
from app.services.api_client import ApiClient
from app.services.ticker_service import TickerService


class StubClient(ApiClient):
    def __init__(self, asset):
        self.asset = asset

    def get_asset(self, ticker):
        return self.asset


def test_normaliza_ticker():
    service = TickerService(StubClient(None))
    assert service.validate("  bbas3 ") == "BBAS3"


@pytest.mark.parametrize("ticker", ["A1LK34", "03BK11", "BBAS3F", "MRSA3BF"])
def test_aceita_tickers_do_catalogo(ticker):
    assert TickerService(StubClient(None)).validate(ticker.lower()) == ticker


@pytest.mark.parametrize("ticker", ["AB/CD3", "PETR4.SA", "A" * 50])
def test_rejeita_formato_de_ticker_invalido(ticker):
    with pytest.raises(ValueError):
        TickerService(StubClient(None)).validate(ticker)


def test_rejeita_ticker_invalido():
    service = TickerService(StubClient(None))
    with pytest.raises(ValueError):
        service.validate("PETR")


def test_ativo_nao_encontrado():
    service = TickerService(StubClient(None))
    with pytest.raises(LookupError, match="Ativo não encontrado"):
        service.get_asset("BBAS3")
