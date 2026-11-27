"""Normalização, agrupamento e merge de cotações diárias."""

import logging
import math

from src.models import Quote
from src.transformers.proventos import parse_date

logger = logging.getLogger(__name__)


def _finite_float(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Valor não finito: {value!r}")
    return number


def normalize_quotes(rows) -> list[Quote]:
    """Normaliza linhas de cotação, deduplica por data e ordena."""
    by_date: dict[str, Quote] = {}
    for row in rows:
        try:
            data = parse_date(row.get("data"))
            close = _finite_float(row.get("close"))
            open_ = _finite_float(row.get("open"))
            high = _finite_float(row.get("high"))
            low = _finite_float(row.get("low"))
            adj_raw = row.get("adj_close")
            adj_close = close if adj_raw is None else _finite_float(adj_raw)
        except (TypeError, ValueError):
            logger.warning("cotacao_invalida", extra={"data": row.get("data")})
            continue
        if data is None:
            logger.warning("cotacao_invalida", extra={"data": row.get("data")})
            continue

        volume_raw = row.get("volume")
        try:
            volume = int(volume_raw) if volume_raw is not None else 0
        except (TypeError, ValueError, OverflowError):
            volume = 0
        if volume < 0 or not math.isfinite(volume):
            volume = 0

        by_date[data] = {
            "data": data,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": adj_close,
            "volume": volume,
        }
    return [by_date[data] for data in sorted(by_date)]


def group_by_year(quotes) -> dict[int, list[Quote]]:
    """Agrupa cotações por ano, preservando a ordem de entrada."""
    grouped: dict[int, list[Quote]] = {}
    for quote in quotes:
        grouped.setdefault(int(quote["data"][:4]), []).append(quote)
    return grouped


def merge_pregoes(existing, new) -> list[Quote]:
    """Une pregões por data; a nova ocorrência vence a antiga."""
    merged = {quote["data"]: quote for quote in existing}
    for quote in new:
        merged[quote["data"]] = quote
    return [merged[data] for data in sorted(merged)]
