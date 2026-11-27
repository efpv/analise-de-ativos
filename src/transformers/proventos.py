"""Normalização de proventos e helpers de data/número usados pelo pipeline."""

import logging
import math
import re
import unicodedata
from datetime import date, datetime

from src.models import EventoProvento, TipoProvento
from src.transformers.ticker import normalize_ticker

logger = logging.getLogger(__name__)

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d")


def parse_date(value: str | date | None) -> str | None:
    """Converte data para ``YYYY-MM-DD``; formatos aceitos: ISO, BR e compacto."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {value!r}")


def _finite_non_negative(number: float, original: object) -> float:
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Valor inválido: {original!r}")
    return number


def parse_brl_number(value: str | int | float | None) -> float | None:
    """Interpreta número no formato brasileiro.

    Aceita ``R$``, espaço/NBSP, parênteses (negativo) e separadores ``.``/``,``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Valor inválido: {value!r}")
    if isinstance(value, (int, float)):
        return _finite_non_negative(float(value), value)

    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace("R$", "").replace("\u00a0", "").replace(" ", "").strip()
    if not text:
        raise ValueError(f"Valor inválido: {value!r}")

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif "." in text:
        # Exatamente 3 dígitos após o ponto indicam separador de milhar
        # ("1.234" -> 1234.0); demais casos são decimais ("0.45" -> 0.45).
        if len(text.rsplit(".", 1)[-1]) == 3:
            text = text.replace(".", "")

    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"Valor inválido: {value!r}") from exc
    if negative:
        number = -number
    return _finite_non_negative(number, value)


def classify(raw_tipo: str | None) -> TipoProvento:
    """Classifica o tipo do provento a partir do texto bruto."""
    text = unicodedata.normalize("NFKD", str(raw_tipo or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).upper()
    if "JCP" in text or "JUROS SOBRE CAPITAL" in text:
        return "JCP"
    if "DIVIDENDO" in text:
        return "DIVIDENDO"
    if "RENDIMENTO" in text:
        return "RENDIMENTO"
    return "OUTRO"


def make_event_id(ticker: str, tipo_provento: str, data_com: str, valor_bruto: float) -> str:
    """Gera um ID determinístico e seguro para documento Firestore."""
    valor = round(float(valor_bruto), 6)
    raw = f"{ticker}_{tipo_provento}_{data_com}_{valor:.6f}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)


def _row_value(row, *keys: str):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def normalize_events(rows, ticker: str) -> list[EventoProvento]:
    """Normaliza, deduplica e ordena eventos de proventos."""
    ticker = normalize_ticker(ticker)
    by_id: dict[str, EventoProvento] = {}
    for row in rows:
        tipo_provento = classify(
            _row_value(row, "tipo_provento", "tipo", "tipoEvento", "tipo_evento")
        )
        data_com = parse_date(_row_value(row, "data_com", "dataCom"))
        if data_com is None:
            logger.warning("provento_sem_data_com", extra={"ticker": ticker})
            continue
        valor_bruto = parse_brl_number(
            _row_value(row, "valor_bruto", "valor", "valorBruto")
        )
        if valor_bruto is None or valor_bruto == 0:
            logger.warning("provento_sem_valor", extra={"ticker": ticker})
            continue
        data_ex = parse_date(_row_value(row, "data_ex", "dataEx"))
        data_pagamento = parse_date(
            _row_value(row, "data_pagamento", "dataPagamento")
        )
        fonte = _row_value(row, "fonte") or "B3"
        evento_id = make_event_id(ticker, tipo_provento, data_com, valor_bruto)
        by_id[evento_id] = {
            "evento_id": evento_id,
            "ticker": ticker,
            "tipo_provento": tipo_provento,
            "data_com": data_com,
            "data_ex": data_ex,
            "data_pagamento": data_pagamento,
            "valor_bruto": round(valor_bruto, 6),
            "fonte": str(fonte),
        }
    return sorted(by_id.values(), key=lambda item: (item["data_com"], item["evento_id"]))
