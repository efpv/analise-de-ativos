"""Extrator de cotações diárias via yfinance."""

import logging

import yfinance as yf

from src.models import Quote
from src.transformers.quotes import normalize_quotes
from src.transformers.ticker import normalize_ticker
from src.utils.retry import retry

logger = logging.getLogger(__name__)

_RETRYABLE: tuple[type[Exception], ...] = (TimeoutError, OSError)
_rate_limit = getattr(getattr(yf, "exceptions", None), "YFRateLimitError", None)
if isinstance(_rate_limit, type) and issubclass(_rate_limit, Exception):
    _RETRYABLE = _RETRYABLE + (_rate_limit,)


def _history(symbol: str, start: str, end: str):
    """Chama ``history`` com os parâmetros da SPEC e fallback de compatibilidade.

    O yfinance 1.8 removeu ``progress`` e ``threads`` da assinatura interna de
    ``PriceHistory.history``. A chamada canônica continua sendo tentada primeiro
    (e é o que os testes verificam); se a versão instalada rejeitar esses
    argumentos, repetimos sem eles.
    """
    kwargs = {
        "start": start,
        "end": end,
        "auto_adjust": False,
        "actions": False,
        "progress": False,
        "threads": False,
    }
    try:
        return yf.Ticker(symbol).history(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if "progress" not in message and "threads" not in message:
            raise
        kwargs.pop("progress", None)
        kwargs.pop("threads", None)
        return yf.Ticker(symbol).history(**kwargs)


def extract(
    ticker: str,
    start: str,
    end: str,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> list[Quote]:
    """Baixa cotações de ``[start, end)``; ``end`` é exclusivo no yfinance."""
    ticker = normalize_ticker(ticker)
    symbol = f"{ticker}.SA"

    frame = retry(
        lambda: _history(symbol, start, end),
        attempts=max_retries,
        base_delay=base_delay,
        retryable=_RETRYABLE,
        logger=logger,
        context={"ticker": ticker, "provider": "yfinance"},
    )
    if frame is None or getattr(frame, "empty", True):
        return []

    frame = frame.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    rows = []
    for index, row in frame.iterrows():
        data = index.date().isoformat() if hasattr(index, "date") else str(index)[:10]
        close = row.get("close")
        rows.append(
            {
                "data": data,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": close,
                "adj_close": row.get("adj_close", close),
                "volume": row.get("volume"),
            }
        )
    return normalize_quotes(rows)
