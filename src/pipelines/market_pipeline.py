"""Pipeline de ingestão de cotações e proventos no Firestore."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from src.config import MarketSettings, collection_name, load_settings
from src.extractors import b3_cotahist, b3_events, yahoo_dividends, yfinance_quotes
from src.extractors.b3_events import B3EventsError
from src.storage.batch_writer import BatchedWriter
from src.storage.firestore_client import get_client
from src.transformers.quotes import group_by_year, merge_pregoes
from src.transformers.ticker import normalize_ticker
from src.utils.dates import full_window, incremental_window, today_b3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickerResult:
    ticker: str
    cotacoes: int
    proventos: int
    erros: tuple[str, ...]
    duracao_ms: int


def _event_date(evento: dict) -> str | None:
    dates = [
        evento.get("data_pagamento"),
        evento.get("data_ex"),
        evento.get("data_com"),
    ]
    valid = [value for value in dates if value]
    return max(valid) if valid else None


def _read_snapshot(reference) -> dict:
    snapshot = reference.get()
    if not getattr(snapshot, "exists", False):
        return {}
    return snapshot.to_dict() or {}


def _run_ticker(
    ticker: str,
    *,
    modo: Literal["full", "incremental"],
    settings: MarketSettings,
    client,
    dry_run: bool,
) -> TickerResult:
    started = time.perf_counter()
    try:
        ticker = normalize_ticker(ticker)
        today = today_b3()
        if modo == "incremental":
            inicio, fim = incremental_window(today, settings.incremental_days)
        else:
            inicio, fim = full_window(today, settings.years)
        end_exclusivo = fim + timedelta(days=1)

        quotes = yfinance_quotes.extract(
            ticker,
            inicio.isoformat(),
            end_exclusivo.isoformat(),
            max_retries=settings.max_retries,
            base_delay=settings.retry_base_delay,
        )
        if settings.cotahist_dir:
            cotahist_quotes = []
            for year in range(inicio.year, fim.year + 1):
                cotahist_quotes.extend(
                    b3_cotahist.extract(ticker, year, settings.cotahist_dir)
                )
            # COTAHIST é a fonte oficial e tem precedência.
            quotes = merge_pregoes(quotes, cotahist_quotes)
        if not quotes:
            logger.warning("sem_cotacoes", extra={"ticker": ticker})

        eventos: list[dict] = []
        if settings.b3_events_url:
            try:
                eventos = b3_events.extract(
                    ticker,
                    inicio.isoformat(),
                    fim.isoformat(),
                    url=settings.b3_events_url,
                    max_retries=settings.max_retries,
                    base_delay=settings.retry_base_delay,
                )
            except B3EventsError:
                logger.warning("b3_events_falhou", extra={"ticker": ticker})
                eventos = []
        if not eventos:
            eventos = yahoo_dividends.extract(
                ticker, inicio.isoformat(), fim.isoformat()
            )
            if eventos:
                logger.warning("yahoo_fallback", extra={"ticker": ticker})
        if not eventos:
            logger.info("sem_proventos", extra={"ticker": ticker})

        grouped = group_by_year(quotes)

        if dry_run:
            logger.info(
                "dry_run_ticker",
                extra={
                    "ticker": ticker,
                    "cotacoes": len(quotes),
                    "proventos": len(eventos),
                    "anos": sorted(grouped),
                },
            )
            return TickerResult(
                ticker=ticker,
                cotacoes=len(quotes),
                proventos=len(eventos),
                erros=(),
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )

        ativos_ref = client.collection(collection_name(settings, "ativos")).document(ticker)
        ativo_data = _read_snapshot(ativos_ref)

        merged_by_year: dict[int, list[dict]] = {}
        quantidade_cotacoes = int(ativo_data.get("quantidade_cotacoes") or 0)
        for ano, novas in grouped.items():
            ano_ref = ativos_ref.collection("cotacoes_anuais").document(str(ano))
            existentes = _read_snapshot(ano_ref).get("pregoes", [])
            merged = merge_pregoes(existentes, novas)
            if not merged:
                continue
            merged_by_year[ano] = merged
            quantidade_cotacoes += len(merged) - len(existentes)

        new_dates = [quote["data"] for quote in quotes]
        inicio_serie = ativo_data.get("inicio_serie")
        fim_serie = ativo_data.get("fim_serie")
        if new_dates:
            inicio_serie = min(
                value for value in (inicio_serie, min(new_dates)) if value
            )
            fim_serie = max(
                value for value in (fim_serie, max(new_dates)) if value
            )

        ultimo_provento_em = ativo_data.get("ultimo_provento_em")
        event_dates = [value for value in (_event_date(event) for event in eventos) if value]
        if event_dates:
            ultimo_provento_em = max(
                value for value in (ultimo_provento_em, max(event_dates)) if value
            )

        if not merged_by_year and not eventos:
            return TickerResult(
                ticker=ticker,
                cotacoes=0,
                proventos=0,
                erros=(),
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )

        atualizado_em = datetime.now(timezone.utc).isoformat()
        proventos_collection = client.collection(collection_name(settings, "proventos"))

        with BatchedWriter(
            client,
            batch_size=settings.batch_size,
            max_retries=settings.max_retries,
            base_delay=settings.retry_base_delay,
        ) as writer:
            for ano, pregoes in merged_by_year.items():
                writer.set(
                    ativos_ref.collection("cotacoes_anuais").document(str(ano)),
                    {
                        "ticker": ticker,
                        "ano": ano,
                        "atualizado_em": atualizado_em,
                        "pregoes": pregoes,
                    },
                    merge=True,
                )
            for evento in eventos:
                writer.set(
                    proventos_collection.document(evento["evento_id"]),
                    dict(evento),
                    merge=True,
                )
            writer.set(
                ativos_ref,
                {
                    "ticker": ticker,
                    "atualizado_em": atualizado_em,
                    "inicio_serie": inicio_serie,
                    "fim_serie": fim_serie,
                    "ultimo_provento_em": ultimo_provento_em,
                    "quantidade_cotacoes": quantidade_cotacoes,
                    "quantidade_proventos": len(eventos),
                },
                merge=True,
            )

        return TickerResult(
            ticker=ticker,
            cotacoes=len(quotes),
            proventos=len(eventos),
            erros=(),
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # isolamento por ticker
        logger.exception("ticker_falhou", extra={"ticker": ticker})
        return TickerResult(
            ticker=ticker,
            cotacoes=0,
            proventos=0,
            erros=(str(exc),),
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )


def run(
    *,
    modo: Literal["full", "incremental"],
    tickers: tuple[str, ...] | None = None,
    settings: MarketSettings | None = None,
    client=None,
    dry_run: bool = False,
) -> tuple[TickerResult, ...]:
    """Executa o pipeline para o universo de tickers informado."""
    settings = settings or load_settings(resolve_adc_project=not dry_run)
    universo = tickers or settings.tickers

    normalized: list[str] = []
    seen: set[str] = set()
    for ticker in universo:
        value = normalize_ticker(ticker)
        if value not in seen:
            seen.add(value)
            normalized.append(value)

    if client is None and not dry_run:
        client = get_client(settings)

    with ThreadPoolExecutor(max_workers=settings.workers) as executor:
        results = list(
            executor.map(
                lambda ticker: _run_ticker(
                    ticker,
                    modo=modo,
                    settings=settings,
                    client=client,
                    dry_run=dry_run,
                ),
                normalized,
            )
        )
    return tuple(results)
