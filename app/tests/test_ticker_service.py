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


def test_rejeita_ticker_invalido():
    service = TickerService(StubClient(None))
    with pytest.raises(ValueError):
        service.validate("PETR")


def test_ativo_nao_encontrado():
    service = TickerService(StubClient(None))
    with pytest.raises(LookupError, match="Ativo não encontrado"):
        service.get_asset("BBAS3")
