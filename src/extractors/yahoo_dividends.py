"""Fallback de proventos via Yahoo Finance.

O Yahoo expõe apenas a data ex-dividendo; ela é usada como ``data_com`` e
``data_ex`` e ``data_pagamento`` fica indisponível.
"""

import logging

import yfinance as yf

from src.models import EventoProvento
from src.transformers.proventos import normalize_events
from src.transformers.ticker import normalize_ticker

logger = logging.getLogger(__name__)

FONTE = "Yahoo Finance (data ex como data_com)"


def extract(ticker: str, start: str, end: str) -> list[EventoProvento]:
    """Extrai a série de dividendos e filtra por ``[start, end]``."""
    ticker = normalize_ticker(ticker)
    series = yf.Ticker(f"{ticker}.SA").dividends
    if series is None or getattr(series, "empty", True):
        return []

    rows = []
    for index, value in series.items():
        data = index.date().isoformat() if hasattr(index, "date") else str(index)[:10]
        if not (start <= data <= end):
            continue
        rows.append(
            {
                "tipo": "OUTRO",
                "data_com": data,
                "data_ex": data,
                "data_pagamento": None,
                "valor": float(value),
                "fonte": FONTE,
            }
        )
    return normalize_events(rows, ticker)
