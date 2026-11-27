"""Leitura de cotações e proventos persistidos no Firestore."""

import logging
from datetime import date

from src.config import MarketSettings, collection_name, load_settings
from src.models import EventoProvento, Quote
from src.storage.firestore_client import get_client
from src.transformers.ticker import normalize_ticker

logger = logging.getLogger(__name__)


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Data inválida: {value!r}") from exc


def get_cotacoes(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    client=None,
    settings: MarketSettings | None = None,
) -> list[Quote]:
    """Retorna cotações no intervalo inclusivo, ordenadas por data."""
    ticker = normalize_ticker(ticker)
    start = _parse_iso_date(start_date)
    end = _parse_iso_date(end_date)
    if start > end:
        raise ValueError("A data inicial não pode ser posterior à data final.")

    settings = settings or load_settings(resolve_adc_project=False)
    client = client or get_client(settings)

    anual = client.collection(collection_name(settings, "ativos")).document(
        ticker
    ).collection("cotacoes_anuais")

    quotes: list[Quote] = []
    for year in range(start.year, end.year + 1):
        snapshot = anual.document(str(year)).get()
        if not getattr(snapshot, "exists", False):
            continue
        pregoes = (snapshot.to_dict() or {}).get("pregoes", [])
        quotes.extend(
            quote for quote in pregoes if start_date <= quote["data"] <= end_date
        )
    quotes.sort(key=lambda quote: quote["data"])
    return quotes


def get_proventos(
    ticker: str,
    start_date: str | None = None,
    *,
    client=None,
    settings: MarketSettings | None = None,
) -> list[EventoProvento]:
    """Retorna proventos do ticker, ordenados por ``data_com``."""
    ticker = normalize_ticker(ticker)
    if start_date is not None:
        _parse_iso_date(start_date)

    settings = settings or load_settings(resolve_adc_project=False)
    client = client or get_client(settings)
    collection = client.collection(collection_name(settings, "proventos"))

    from google.api_core.exceptions import FailedPrecondition
    from google.cloud.firestore_v1.base_query import FieldFilter

    fallback = False
    try:
        query = collection.where(filter=FieldFilter("ticker", "==", ticker))
        if start_date:
            query = query.where(filter=FieldFilter("data_com", ">=", start_date))
        query = query.order_by("data_com")
        documents = list(query.stream())
    except FailedPrecondition:
        logger.warning("indice_proventos_ausente", extra={"ticker": ticker})
        fallback = True
        documents = list(collection.stream())

    eventos: list[EventoProvento] = []
    for document in documents:
        data = document.to_dict() or {}
        if (data.get("ticker") or "").upper() != ticker:
            continue
        if start_date and (data.get("data_com") or "") < start_date:
            continue
        eventos.append(
            {
                "evento_id": data.get("evento_id") or document.id,
                "ticker": data.get("ticker") or ticker,
                "tipo_provento": data.get("tipo_provento") or "OUTRO",
                "data_com": data.get("data_com"),
                "data_ex": data.get("data_ex"),
                "data_pagamento": data.get("data_pagamento"),
                "valor_bruto": data.get("valor_bruto", 0.0),
                "fonte": data.get("fonte") or "",
            }
        )

    if fallback:
        logger.warning("indice_proventos_fallback", extra={"ticker": ticker})
    eventos.sort(key=lambda item: (item.get("data_com") or "", item.get("evento_id") or ""))
    return eventos
