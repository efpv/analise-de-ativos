"""CLI do pipeline de mercado, executável como Cloud Run Job."""

import argparse
import logging
import os
import time

from src.config import ConfigurationError, load_settings
from src.pipelines.market_pipeline import run
from src.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Ingestão de cotações e proventos da B3 no Firestore.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="Carga de MARKET_YEARS anos.")
    mode.add_argument(
        "--incremental", action="store_true", help="Carga dos últimos MARKET_INCREMENTAL_DAYS dias."
    )
    parser.add_argument("--tickers", help="Lista CSV de tickers.")
    parser.add_argument("--catalog", action="store_true", help="Usa o catálogo local.")
    parser.add_argument("--catalog-path", help="Caminho do catálogo local.")
    parser.add_argument("--tickers-file", help="Arquivo .json ou .txt de tickers.")
    parser.add_argument("--years", type=int, help="Anos da carga full.")
    parser.add_argument("--days", type=int, help="Dias da carga incremental.")
    parser.add_argument("--cotahist-dir", help="Diretório dos arquivos COTAHIST.")
    parser.add_argument("--project", help="Projeto Google Cloud.")
    parser.add_argument("--database", help="Banco Firestore.")
    parser.add_argument("--workers", type=int, help="Paralelismo por ticker.")
    parser.add_argument("--dry-run", action="store_true", help="Não escreve no Firestore.")
    parser.add_argument("--log-level", default="INFO", help="Nível do log JSON.")
    return parser


def _apply_overrides(env: dict[str, str], args: argparse.Namespace) -> None:
    if args.tickers:
        env["MARKET_TICKERS"] = args.tickers
        env.pop("MARKET_TICKERS_FILE", None)
    if args.tickers_file:
        env["MARKET_TICKERS_FILE"] = args.tickers_file
        env.pop("MARKET_TICKERS", None)
    if args.catalog:
        env["MARKET_TICKERS_FROM_CATALOG"] = "true"
        env.pop("MARKET_TICKERS_FILE", None)
        env.pop("MARKET_TICKERS", None)
    if args.catalog_path:
        env["MARKET_CATALOG_PATH"] = args.catalog_path
    if args.years is not None:
        env["MARKET_YEARS"] = str(args.years)
    if args.days is not None:
        env["MARKET_INCREMENTAL_DAYS"] = str(args.days)
    if args.cotahist_dir:
        env["MARKET_B3_COTAHIST_DIR"] = args.cotahist_dir
    if args.project:
        env["GOOGLE_CLOUD_PROJECT"] = args.project
    if args.database:
        env["FIRESTORE_DATABASE"] = args.database
    if args.workers is not None:
        env["MARKET_WORKERS"] = str(args.workers)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    modo = "incremental" if args.incremental else "full"

    env = dict(os.environ)
    _apply_overrides(env, args)

    try:
        settings = load_settings(env=env, resolve_adc_project=not args.dry_run)
    except ConfigurationError as exc:
        logger.error("configuracao_invalida", extra={"erro": str(exc)})
        return 2

    started = time.perf_counter()
    try:
        results = run(
            modo=modo,
            tickers=settings.tickers,
            settings=settings,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        logger.error("execucao_interrompida")
        return 1

    falhas = sum(1 for result in results if result.erros)
    logger.info(
        "execucao_concluida",
        extra={
            "modo": modo,
            "tickers": len(results),
            "falhas": falhas,
            "duracao_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return 1 if falhas else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
