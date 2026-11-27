"""Configuração do pipeline de mercado, sem estado global.

Cada chamada de :func:`load_settings` lê o ambiente (ou um ``env`` injetado) e
devolve um :class:`MarketSettings` imutável. A resolução de projeto via ADC é
opcional e nunca acontece no caminho de leitura da API.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from src.transformers.catalog import catalog_tickers
from src.transformers.ticker import normalize_ticker

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TICKERS = "ITUB4,BBAS3,WEGE3,VALE3"
_DEFAULT_TICKERS = DEFAULT_TICKERS
_TRUE_VALUES = frozenset({"true", "1", "yes"})


class ConfigurationError(ValueError):
    """Configuração inválida; o CLI converte em exit code 2."""


@dataclass(frozen=True)
class MarketSettings:
    tickers: tuple[str, ...]
    tickers_from_catalog: bool
    tickers_file: str
    catalog_path: str
    years: int
    incremental_days: int
    max_range_days: int
    google_cloud_project: str
    firestore_database: str
    collection_prefix: str
    cotahist_dir: str
    b3_events_url: str
    batch_size: int
    max_retries: int
    retry_base_delay: float
    workers: int
    admin_token: str


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def _as_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ConfigurationError(f"{key} deve ser um número inteiro.") from exc


def _as_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError as exc:
        raise ConfigurationError(f"{key} deve ser um número.") from exc


def _resolve_repo_path(value: str) -> str:
    if not value:
        return value
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    return str(_REPO_ROOT / candidate)


def _parse_ticker_csv(value: str) -> tuple[str, ...]:
    tickers: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        text = item.strip()
        if not text:
            continue
        normalized = normalize_ticker(text)
        if normalized not in seen:
            seen.add(normalized)
            tickers.append(normalized)
    return tuple(tickers)


def pilot_tickers(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Universo do piloto (4 tickers), configurável por ``MARKET_TICKERS``.

    Ignora ``MARKET_TICKERS_FROM_CATALOG`` e ``MARKET_TICKERS_FILE``: o piloto é
    sempre a lista curta usada para validação rápida.
    """
    source = os.environ if env is None else env
    raw = (source.get("MARKET_TICKERS") or "").strip() or DEFAULT_TICKERS
    return _parse_ticker_csv(raw) or _parse_ticker_csv(DEFAULT_TICKERS)


def read_tickers_file(path: str | Path) -> tuple[str, ...]:
    """Lê tickers de um ``.json`` (strings ou objetos com ``ticker``) ou ``.txt``."""
    file_path = Path(path)
    try:
        if file_path.suffix.lower() == ".json":
            with file_path.open(encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, list):
                raise ConfigurationError("O arquivo de tickers deve conter uma lista.")
            raw_items = [
                item.get("ticker") if isinstance(item, dict) else item
                for item in payload
            ]
        else:
            raw_items = [
                line.strip()
                for line in file_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
    except ConfigurationError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Não foi possível ler o arquivo de tickers: {path}") from exc

    tickers: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if item is None:
            continue
        try:
            normalized = normalize_ticker(str(item))
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
        if normalized not in seen:
            seen.add(normalized)
            tickers.append(normalized)
    if not tickers:
        raise ConfigurationError("O arquivo de tickers está vazio.")
    return tuple(tickers)


def _resolve_project(env: Mapping[str, str], resolve_adc_project: bool) -> str:
    project = (env.get("GOOGLE_CLOUD_PROJECT") or "").strip() or (
        env.get("FIRESTORE_PROJECT") or ""
    ).strip()
    if project:
        return project
    if not resolve_adc_project:
        return ""
    try:
        import google.auth

        _, default_project = google.auth.default()
    except Exception as exc:  # credenciais ausentes ou inválidas
        raise ConfigurationError(
            "Projeto Google Cloud não configurado e ADC indisponível."
        ) from exc
    return default_project or ""


def load_settings(
    *,
    env: Mapping[str, str] | None = None,
    resolve_adc_project: bool = True,
) -> MarketSettings:
    """Monta e valida as configurações do pipeline."""
    source = dict(env if env is not None else os.environ)

    years = _as_int(source, "MARKET_YEARS", 5)
    if years <= 0:
        raise ConfigurationError("MARKET_YEARS deve ser maior que zero.")

    incremental_days = _as_int(source, "MARKET_INCREMENTAL_DAYS", 60)
    if incremental_days <= 0:
        raise ConfigurationError("MARKET_INCREMENTAL_DAYS deve ser maior que zero.")

    max_range_days = _as_int(source, "MARKET_MAX_RANGE_DAYS", 3650)
    if max_range_days <= 0:
        raise ConfigurationError("MARKET_MAX_RANGE_DAYS deve ser maior que zero.")

    max_retries = _as_int(source, "MARKET_MAX_RETRIES", 3)
    if max_retries < 0:
        raise ConfigurationError("MARKET_MAX_RETRIES não pode ser negativo.")

    workers = _as_int(source, "MARKET_WORKERS", 2)
    if workers < 1:
        raise ConfigurationError("MARKET_WORKERS deve ser pelo menos 1.")

    batch_size = _as_int(source, "MARKET_BATCH_SIZE", 500)
    if batch_size < 1:
        raise ConfigurationError("MARKET_BATCH_SIZE deve ser pelo menos 1.")
    if batch_size > 500:
        batch_size = 500
        logger.warning("batch_size_ajustado", extra={"batch_size": 500})

    retry_base_delay = _as_float(source, "MARKET_RETRY_BACKOFF", 1.0)
    if retry_base_delay <= 0:
        raise ConfigurationError("MARKET_RETRY_BACKOFF deve ser maior que zero.")

    tickers_from_catalog = _as_bool(source.get("MARKET_TICKERS_FROM_CATALOG"))
    tickers_file = (source.get("MARKET_TICKERS_FILE") or "").strip()
    catalog_path = (source.get("MARKET_CATALOG_PATH") or "data/ativos_b3.json").strip()

    try:
        if tickers_from_catalog:
            tickers = catalog_tickers(_resolve_repo_path(catalog_path))
        elif tickers_file:
            tickers = read_tickers_file(tickers_file)
        else:
            tickers = _parse_ticker_csv(source.get("MARKET_TICKERS", _DEFAULT_TICKERS))
    except ConfigurationError:
        raise
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ConfigurationError(f"Não foi possível carregar o universo de tickers: {exc}") from exc

    if not tickers:
        raise ConfigurationError("Nenhum universo de tickers configurado.")

    collection_prefix = (
        (source.get("MARKET_FIRESTORE_PREFIX") or "").strip()
        or (source.get("FIRESTORE_PREFIX") or "").strip()
    )

    return MarketSettings(
        tickers=tickers,
        tickers_from_catalog=tickers_from_catalog,
        tickers_file=tickers_file,
        catalog_path=catalog_path,
        years=years,
        incremental_days=incremental_days,
        max_range_days=max_range_days,
        google_cloud_project=_resolve_project(source, resolve_adc_project),
        firestore_database=(source.get("FIRESTORE_DATABASE") or "(default)").strip()
        or "(default)",
        collection_prefix=collection_prefix,
        cotahist_dir=(source.get("MARKET_B3_COTAHIST_DIR") or "").strip(),
        b3_events_url=(source.get("MARKET_B3_EVENTS_URL") or "").strip(),
        batch_size=batch_size,
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
        workers=workers,
        admin_token=(source.get("MARKET_ADMIN_TOKEN") or "").strip(),
    )


def collection_name(settings: MarketSettings, name: str) -> str:
    """Aplica o prefixo efetivo ao nome da coleção."""
    return f"{settings.collection_prefix}{name}"
