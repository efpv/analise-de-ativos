"""Extrator de proventos da fonte oficial da B3.

A URL e o schema reais da B3 ainda precisam ser confirmados (§11 da SPEC). Sem
``MARKET_B3_EVENTS_URL``, a extração é pulada com aviso e o pipeline usa o
fallback do Yahoo.
"""

import logging

import httpx

from src.models import EventoProvento
from src.transformers.proventos import normalize_events, parse_date
from src.utils.retry import retry

logger = logging.getLogger(__name__)

_FIELD_ALIASES = {
    "ticker": ("ticker", "codigo"),
    "tipo": ("tipo", "tipoEvento", "tipo_provento"),
    "data_com": ("dataCom", "data_com"),
    "data_ex": ("dataEx", "data_ex"),
    "data_pagamento": ("dataPagamento", "data_pagamento"),
    "valor": ("valor", "valorBruto", "valor_bruto"),
    "fonte": ("fonte",),
}
_ENVELOPE_KEYS = ("results", "data", "eventos")


class B3EventsError(RuntimeError):
    """Falha ao consultar ou interpretar a fonte oficial de proventos."""


class _RetryableB3Error(RuntimeError):
    """Erro transitório da B3 que deve ser repetido."""


def _first(payload: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


class B3EventsPayloadParser:
    """Único ponto que conhece o schema da B3."""

    def parse(self, payload: object, ticker: str, start: str, end: str) -> list[dict]:
        if isinstance(payload, dict):
            for key in _ENVELOPE_KEYS:
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
            else:
                raise B3EventsError("Payload da B3 sem lista de eventos.")
        if not isinstance(payload, list):
            raise B3EventsError("Payload da B3 inválido.")

        rows: list[dict] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                data_com = parse_date(_first(item, _FIELD_ALIASES["data_com"]))
            except ValueError:
                logger.warning("provento_data_invalida", extra={"ticker": ticker})
                continue
            if data_com is None or not (start <= data_com <= end):
                continue
            rows.append(
                {
                    "tipo": _first(item, _FIELD_ALIASES["tipo"]),
                    "data_com": data_com,
                    "data_ex": _first(item, _FIELD_ALIASES["data_ex"]),
                    "data_pagamento": _first(item, _FIELD_ALIASES["data_pagamento"]),
                    "valor": _first(item, _FIELD_ALIASES["valor"]),
                    "fonte": _first(item, _FIELD_ALIASES["fonte"]) or "B3",
                }
            )
        return rows


def _fetch(url: str, ticker: str, start: str, end: str, client: httpx.Client) -> object:
    response = client.get(
        url,
        params={"ticker": ticker, "dataInicio": start, "dataFim": end},
        timeout=10.0,
    )
    if response.status_code == 429 or response.status_code >= 500:
        raise _RetryableB3Error(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        raise B3EventsError(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise B3EventsError("Resposta da B3 não é JSON válido.") from exc


def extract(
    ticker: str,
    start: str,
    end: str,
    *,
    url: str,
    client: httpx.Client | None = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> list[EventoProvento]:
    """Consulta a B3 e normaliza os eventos; URL vazia devolve ``[]``."""
    if not url:
        logger.warning("b3_events_sem_url", extra={"ticker": ticker})
        return []

    owned_client = client is None
    http_client = client or httpx.Client()
    try:
        try:
            payload = retry(
                lambda: _fetch(url, ticker, start, end, http_client),
                attempts=max_retries,
                base_delay=base_delay,
                retryable=(_RetryableB3Error, httpx.TimeoutException, OSError),
                logger=logger,
                context={"ticker": ticker, "provider": "b3"},
            )
        except (B3EventsError, httpx.HTTPError, OSError) as exc:
            raise B3EventsError("Falha ao consultar a fonte oficial de proventos.") from exc
        except _RetryableB3Error as exc:
            raise B3EventsError("Falha ao consultar a fonte oficial de proventos.") from exc

        rows = B3EventsPayloadParser().parse(payload, ticker, start, end)
        try:
            return normalize_events(rows, ticker)
        except ValueError as exc:
            raise B3EventsError("Payload da B3 contém dados inválidos.") from exc
    finally:
        if owned_client:
            http_client.close()
