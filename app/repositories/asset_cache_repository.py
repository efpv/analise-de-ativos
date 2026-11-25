from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import sqlite3
from pathlib import Path

from app.core.config import settings
from app.models.valuation import AssetData


@dataclass(frozen=True)
class CachedAsset:
    ticker: str
    encontrado: bool
    dividendos_em: datetime
    asset: AssetData | None
    preco_em: datetime | None


class AssetCacheRepository:
    """Guarda preço e dividendos anuais por ativo para evitar consultas repetidas às fontes."""

    def __init__(self, database_path: str | None = None) -> None:
        self.database_path = database_path or settings.database_path
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS asset_cache (
                    ticker TEXT PRIMARY KEY,
                    encontrado INTEGER NOT NULL,
                    empresa TEXT,
                    fonte TEXT,
                    preco REAL,
                    preco_em TEXT,
                    dividendos_em TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS asset_dividends (
                    ticker TEXT NOT NULL,
                    ano INTEGER NOT NULL,
                    valor REAL NOT NULL,
                    PRIMARY KEY (ticker, ano)
                )
                """
            )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, ticker: str) -> CachedAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encontrado, empresa, fonte, preco, preco_em, dividendos_em FROM asset_cache WHERE ticker = ?",
                (ticker,),
            ).fetchone()
            if row is None:
                return None
            found, company, source, price, price_at, dividends_at = row
            asset = None
            if found:
                history = dict(connection.execute(
                    "SELECT ano, valor FROM asset_dividends WHERE ticker = ?", (ticker,)
                ).fetchall())
                asset = AssetData(
                    ticker=ticker, empresa=company, preco_atual=price, dividend_yield=None,
                    dividendos_historicos=history, fonte=source,
                )
            return CachedAsset(
                ticker=ticker,
                encontrado=bool(found),
                dividendos_em=datetime.fromisoformat(dividends_at),
                asset=asset,
                preco_em=datetime.fromisoformat(price_at) if price_at else None,
            )

    def save_asset(self, asset: AssetData, now: datetime) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO asset_cache (ticker, encontrado, empresa, fonte, preco, preco_em, dividendos_em) "
                "VALUES (?, 1, ?, ?, ?, ?, ?)",
                (asset.ticker, asset.empresa, asset.fonte, asset.preco_atual, now.isoformat(), now.isoformat()),
            )
            connection.execute("DELETE FROM asset_dividends WHERE ticker = ?", (asset.ticker,))
            connection.executemany(
                "INSERT INTO asset_dividends (ticker, ano, valor) VALUES (?, ?, ?)",
                [(asset.ticker, year, value) for year, value in asset.dividendos_historicos.items()],
            )

    def save_missing(self, ticker: str, now: datetime) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO asset_cache (ticker, encontrado, dividendos_em) VALUES (?, 0, ?)",
                (ticker, now.isoformat()),
            )
            connection.execute("DELETE FROM asset_dividends WHERE ticker = ?", (ticker,))

    def update_price(self, ticker: str, price: float, now: datetime) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE asset_cache SET preco = ?, preco_em = ? WHERE ticker = ? AND encontrado = 1",
                (price, now.isoformat(), ticker),
            )
