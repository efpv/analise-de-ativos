import re
from app.models.valuation import AssetData
from app.services.api_client import ApiClient


class TickerService:
    def __init__(self, client: ApiClient | None = None) -> None:
        self.client = client or ApiClient()

    def validate(self, ticker: str) -> str:
        normalized = ticker.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{4}[0-9]{1,2}[A-Z]?F?", normalized):
            raise ValueError("Informe um ticker válido da B3, por exemplo BBAS3.")
        return normalized

    def get_asset(self, ticker: str) -> AssetData:
        normalized = self.validate(ticker)
        asset = self.client.get_asset(normalized)
        if asset is None:
            raise LookupError("Ativo não encontrado.")
        return asset

    def get_price(self, ticker: str) -> float | None:
        return self.client.get_price(self.validate(ticker))
