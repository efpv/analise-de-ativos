from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.repositories.valuation_repository import ValuationRepository
from app.models.valuation import DividendPeriod, Valuation
from app.schemas.valuation import (
    ComparisonResponse,
    DividendHistory,
    DividendPaymentResponse,
    DividendSummary,
    ProfilePrices,
    RankingResponse,
    ValuationResponse,
)
from app.services.ticker_service import TickerService
from app.services.sector_peer_service import SectorPeerService
from app.services.valuation_service import ValuationService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
repository = ValuationRepository()
ticker_service = TickerService()
valuation_service = ValuationService()
sector_peer_service = SectorPeerService()
RANKING_TICKERS = ("BBAS3", "BBSE3", "ITSA4", "PETR4", "TAEE11", "CMIG4", "TRPL4", "SAPR4")


@router.get("/api/v1/assets", response_class=FileResponse, include_in_schema=False)
def get_assets_catalog():
    return FileResponse(
        Path(__file__).resolve().parents[2] / "data" / "ativos_b3.json",
        media_type="application/json",
    )


def _calculate(
    ticker: str, taxa: float | None = None, periodo: DividendPeriod = "5anos"
) -> Valuation:
    asset = ticker_service.get_asset(ticker)
    return valuation_service.calculate(asset, taxa, periodo)


def _response(valuation: Valuation) -> ValuationResponse:
    sector, peers = sector_peer_service.get_peers(valuation.ticker)
    history = sorted(valuation.dividendos_historicos.items())
    annual = valuation.periodo != "ltm"
    growth = None
    if annual and len(history) > 1 and all(year in valuation.anos_registrados for year, _ in history) and all(
        previous_value > 0 and year == previous_year + 1
        for (previous_year, previous_value), (year, _) in zip(history, history[1:])
    ):
        growth = sum(
            (value / previous_value - 1) * 100
            for (_, previous_value), (_, value) in zip(history, history[1:])
        ) / (len(history) - 1)
    return ValuationResponse(
        ticker=valuation.ticker,
        empresa=valuation.empresa,
        preco_atual=round(valuation.preco_atual, 8),
        dividend_yield=round(valuation.dividend_yield, 4),
        dividendos_historicos=[
            DividendHistory(
                ano=ano, valor=round(valor, 8),
                situacao=(
                    "parcial" if not annual or ano == valuation.data_consulta.astimezone().year
                    else "sem_registro" if ano not in valuation.anos_registrados else "encerrado"
                ),
            )
            for ano, valor in history
        ],
        dividendos_medios=round(valuation.dividendos_medios, 8),
        taxa_bazin=valuation.taxa_bazin,
        preco_justo=round(valuation.preco_justo, 8),
        margem_seguranca=round(valuation.margem_seguranca, 4),
        status=valuation.status,
        fonte=valuation.fonte,
        data_consulta=valuation.data_consulta,
        avisos=list(valuation.avisos),
        setor=sector,
        ativos_comparaveis=peers,
        periodo=valuation.periodo,
        dividendos_ltm=round(valuation.dividendos_ltm, 8) if valuation.dividendos_ltm is not None else None,
        pagamentos_ltm=(
            [DividendPaymentResponse(data=item.data, valor=round(item.valor, 8)) for item in valuation.pagamentos_ltm]
            if valuation.pagamentos_ltm is not None else None
        ),
        ano_dividend_yield=valuation.ano_dividend_yield,
        dividendos_dividend_yield=round(valuation.dividendos_dividend_yield, 8),
        eventos_encontrados=valuation.eventos_encontrados,
        resumo_dividendos=DividendSummary(
            anos_analisados=len(history) if annual else None,
            maior_anual=round(max(value for _, value in history), 8) if annual and history else None,
            menor_anual=round(min(value for _, value in history), 8) if annual and history else None,
            crescimento_medio=round(growth, 4) if growth is not None else None,
        ),
        precos_perfil=ProfilePrices(
            agressivo=round(valuation.dividendos_medios / 0.06, 8),
            moderado=round(valuation.dividendos_medios / 0.08, 8),
            conservador=round(valuation.dividendos_medios / 0.10, 8),
        ),
    )


@router.get("/api/v1/valuation/{ticker}", response_model=ValuationResponse)
def get_valuation(
    ticker: str, taxa: float | None = Query(default=None, ge=0.001, le=1),
    periodo: DividendPeriod = Query(default="5anos"),
):
    try:
        valuation = _calculate(ticker, taxa, periodo)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repository.add(valuation.ticker, valuation.preco_atual, valuation.preco_justo)
    return _response(valuation)


@router.get("/api/v1/ranking", response_model=RankingResponse)
def get_ranking(
    ordem: Literal["potencial", "dy", "classificacao"] = Query(default="potencial"),
    taxa: float | None = Query(default=None, ge=0.001, le=1),
    periodo: DividendPeriod = Query(default="5anos"),
):
    if not settings.ranking_enabled:
        raise HTTPException(status_code=503, detail="O ranking está temporariamente desativado para reduzir consultas.")

    results: list[Valuation] = []
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {ticker: executor.submit(_calculate, ticker, taxa, periodo) for ticker in RANKING_TICKERS}
        for ticker, future in futures.items():
            try:
                results.append(future.result())
            except (LookupError, ValueError) as exc:
                warnings.append(f"{ticker}: {exc}")

    classifications = {
        "Muito Barata": 0,
        "Barata": 1,
        "Justa": 2,
        "Cara": 3,
        "Muito Cara": 4,
    }
    if ordem == "dy":
        results.sort(key=lambda item: item.dividend_yield, reverse=True)
    elif ordem == "classificacao":
        results.sort(key=lambda item: (classifications[item.status], -item.margem_seguranca))
    else:
        results.sort(key=lambda item: item.margem_seguranca, reverse=True)

    return RankingResponse(
        itens=[_response(item) for item in results],
        ordem=ordem,
        avisos=warnings,
    )


@router.get("/api/v1/comparison", response_model=ComparisonResponse)
def compare_assets(
    tickers: list[str] = Query(...),
    taxa: float | None = Query(default=None, ge=0.001, le=1),
    periodo: DividendPeriod = Query(default="5anos"),
):
    if not 1 <= len(tickers) <= 4:
        raise HTTPException(status_code=400, detail="Selecione entre 1 e 4 ativos para comparar.")

    try:
        normalized = [ticker_service.validate(ticker) for ticker in tickers]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if len(set(normalized)) != len(normalized):
        raise HTTPException(status_code=400, detail="Remova tickers duplicados da comparação.")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_calculate, ticker, taxa, periodo) for ticker in normalized]
        results: list[Valuation] = []
        warnings: list[str] = []
        for ticker, future in zip(normalized, futures):
            try:
                results.append(future.result())
            except LookupError as exc:
                warnings.append(f"{ticker}: {exc}")
            except ValueError as exc:
                warnings.append(f"{ticker}: {exc}")

    return ComparisonResponse(
        itens=[_response(item) for item in results],
        avisos=warnings,
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"history": repository.recent(), "ranking_enabled": settings.ranking_enabled},
    )


@router.get("/ranking", response_class=HTMLResponse)
def ranking_page(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"history": repository.recent(), "ranking_enabled": settings.ranking_enabled},
    )
