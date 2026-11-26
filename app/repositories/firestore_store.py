from dataclasses import asdict
from datetime import datetime

from app.core.config import settings
from app.models.valuation import AssetData, Fundamentals
from app.repositories.asset_cache_repository import CachedAsset


def create_client():
    from google.cloud import firestore

    return firestore.Client(project=settings.firestore_project or None)


class FirestoreAssetCache:
    """Mesma interface de AssetCacheRepository, com os dados fora do disco da instância."""

    def __init__(self, client=None) -> None:
        self._client = client

    @property
    def collection(self):
        if self._client is None:
            self._client = create_client()
        return self._client.collection(f"{settings.firestore_prefix}asset_cache")

    def get(self, ticker: str) -> CachedAsset | None:
        snapshot = self.collection.document(ticker).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        found = bool(data["encontrado"])
        asset = None
        if found:
            asset = AssetData(
                ticker=ticker, empresa=data["empresa"], preco_atual=data["preco"], dividend_yield=None,
                dividendos_historicos={int(year): value for year, value in data["dividendos"].items()},
                fonte=data["fonte"],
                fundamentos=Fundamentals(**data["fundamentos"]) if data.get("fundamentos") else None,
            )
        price_at = data.get("preco_em")
        return CachedAsset(
            ticker=ticker, encontrado=found, dividendos_em=datetime.fromisoformat(data["dividendos_em"]),
            asset=asset, preco_em=datetime.fromisoformat(price_at) if price_at else None,
        )

    def save_asset(self, asset: AssetData, now: datetime) -> None:
        self.collection.document(asset.ticker).set({
            "encontrado": True, "empresa": asset.empresa, "fonte": asset.fonte,
            "preco": asset.preco_atual, "preco_em": now.isoformat(), "dividendos_em": now.isoformat(),
            "dividendos": {str(year): value for year, value in asset.dividendos_historicos.items()},
            "fundamentos": asdict(asset.fundamentos) if asset.fundamentos else None,
        })

    def save_missing(self, ticker: str, now: datetime) -> None:
        self.collection.document(ticker).set({"encontrado": False, "dividendos_em": now.isoformat()})

    def update_price(self, ticker: str, price: float, now: datetime) -> None:
        self.collection.document(ticker).update({"preco": price, "preco_em": now.isoformat()})


    def update_fundamentals(self, ticker: str, fundamentals: Fundamentals) -> None:
        self.collection.document(ticker).update({"fundamentos": asdict(fundamentals)})


class FirestoreStateStore:
    """Guarda a lista pronta e o progresso da varredura, compartilhados entre instâncias."""

    def __init__(self, client=None) -> None:
        self._client = client

    def _document(self, name: str):
        if self._client is None:
            self._client = create_client()
        return self._client.collection(f"{settings.firestore_prefix}cash_yield").document(name)

    def get_snapshot(self) -> dict | None:
        snapshot = self._document("snapshot").get()
        return snapshot.to_dict() if snapshot.exists else None

    def set_snapshot(self, data: dict) -> None:
        self._document("snapshot").set(data)

    def get_progress(self) -> dict | None:
        snapshot = self._document("progress").get()
        return snapshot.to_dict() if snapshot.exists else None

    def set_progress(self, data: dict) -> None:
        self._document("progress").set(data)
