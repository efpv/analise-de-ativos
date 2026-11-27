"""Extrator de cotações a partir do arquivo COTAHIST da B3."""

import logging
from pathlib import Path

from src.models import Quote
from src.transformers.quotes import normalize_quotes
from src.transformers.ticker import normalize_ticker

logger = logging.getLogger(__name__)


def _price(line: str, start: int, end: int) -> float:
    return int(line[start:end]) / 100


def extract(ticker: str, year: int, directory: str | Path) -> list[Quote]:
    """Lê ``COTAHIST_A{ano}.TXT`` e devolve os pregões do ticker."""
    ticker = normalize_ticker(ticker)
    path = Path(directory) / f"COTAHIST_A{year}.TXT"
    if not path.exists():
        logger.warning("cotahist_ausente", extra={"ano": year})
        return []

    rows: list[dict] = []
    with path.open(encoding="latin-1") as file:
        for line in file:
            if len(line) < 128 or line[0:2] != "01":
                continue
            if line[12:24].strip() != ticker:
                continue
            try:
                data = line[2:10]
                rows.append(
                    {
                        "data": data,
                        "open": _price(line, 56, 63),
                        "high": _price(line, 63, 70),
                        "low": _price(line, 70, 77),
                        "close": _price(line, 84, 91),
                        "adj_close": _price(line, 84, 91),
                        "volume": int(line[115:128]),
                    }
                )
            except ValueError:
                continue

    if rows:
        logger.warning("adj_close_igual_close", extra={"ticker": ticker, "ano": year})
    return normalize_quotes(rows)
