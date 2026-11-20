import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, datetime
from math import isfinite

import httpx

from app.core.config import settings
from app.models.valuation import AssetData, DividendPayment

logger = logging.getLogger(__name__)

try:
    from yfinance.exceptions import YFException
except ImportError:
    YAHOO_EXCEPTIONS: tuple[type[BaseException], ...] = ()
else:
    YAHOO_EXCEPTIONS = (YFException,)


class ApiClient:
    def __init__(self) -> None:
        self.timeout = settings.request_timeout

    def get_asset(self, ticker: str) -> AssetData | None:
        try:
            asset = asyncio.run(self._from_brapi(ticker))
            if asset and any(asset.dividendos_historicos.values()):
                return asset
            if asset:
                logger.warning(
                    "BRAPI sem histórico de dividendos: ticker=%s; consultando Yahoo Finance",
                    ticker,
                    extra={"ticker": ticker, "provider": "brapi"},
                )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Falha na consulta à BRAPI: ticker=%s status_http=%s tipo=%s",
                ticker, exc.response.status_code, type(exc).__name__,
                extra={"ticker": ticker, "provider": "brapi", "status_http": exc.response.status_code},
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.warning(
                "Falha na consulta à BRAPI: ticker=%s tipo=%s",
                ticker, type(exc).__name__,
                extra={"ticker": ticker, "provider": "brapi", "error_type": type(exc).__name__},
            )

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._from_yahoo, ticker)
                asset = future.result(timeout=8.0)
                if asset is None:
                    logger.warning(
                        "Yahoo Finance não retornou dados válidos: ticker=%s",
                        ticker,
                        extra={"ticker": ticker, "provider": "yahoo"},
                    )
                return asset
        except TimeoutError:
            logger.warning(
                "Timeout no fallback Yahoo Finance: ticker=%s",
                ticker,
                extra={"ticker": ticker, "provider": "yahoo"},
            )
        except YAHOO_EXCEPTIONS + (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RuntimeError,
        ) as exc:
            logger.warning(
                "Falha no fallback Yahoo Finance: ticker=%s tipo=%s",
                ticker, type(exc).__name__,
                extra={"ticker": ticker, "provider": "yahoo", "error_type": type(exc).__name__},
            )
        return None

    async def _from_brapi(self, ticker: str) -> AssetData | None:
        url = f"https://brapi.dev/api/quote/{ticker}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = {"Authorization": f"Bearer {settings.brapi_api_key}"} if settings.brapi_api_key else {}
            response = await client.get(
                url, params={"dividends": "true", "fundamental": "true"}, headers=headers
            )
            if response.status_code == 404:
                logger.warning(
                    "BRAPI não retornou o ativo: ticker=%s status_http=404",
                    ticker,
                    extra={"ticker": ticker, "provider": "brapi", "status_http": 404},
                )
                return None
            response.raise_for_status()

        results = response.json().get("results") or []
        if not results:
            logger.warning(
                "BRAPI retornou resultado vazio: ticker=%s",
                ticker,
                extra={"ticker": ticker, "provider": "brapi"},
            )
            return None
        item = results[0]
        price = item.get("regularMarketPrice") or item.get("regularMarketPreviousClose")
        if not price:
            logger.warning(
                "BRAPI não retornou preço: ticker=%s",
                ticker,
                extra={"ticker": ticker, "provider": "brapi"},
            )
            return None

        raw_history = item.get("dividends") or item.get("dividendsData") or item.get("dividendData") or []
        history, warnings, payments, event_count = self._parse_dividends(raw_history)
        raw_yield = item.get("dividendYield")
        normalized_yield = self._normalize_yield(raw_yield)
        if raw_yield is not None and normalized_yield is None:
            warnings.append("O Dividend Yield retornado pela BRAPI foi ignorado por conter valor inválido.")
        return AssetData(
            ticker=ticker,
            empresa=self._normalize_text(
                item.get("longName") or item.get("shortName"),
                ticker,
            ),
            preco_atual=float(price),
            dividend_yield=normalized_yield,
            dividendos_historicos=history,
            fonte="BRAPI",
            avisos=tuple(warnings),
            pagamentos=payments,
            eventos_encontrados=event_count,
        )

    def _from_yahoo(self, ticker: str) -> AssetData | None:
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("Biblioteca yfinance não está instalada.")
            return None

        stock = yf.Ticker(f"{ticker}.SA")
        fast_info = stock.fast_info
        price = fast_info.get("last_price") or fast_info.get("regular_market_price")
        if not price:
            info = stock.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price:
            return None

        info = stock.info
        dividends = stock.dividends
        history: dict[int, float] = {}
        warnings: list[str] = []
        event_count = 0
        if dividends is not None:
            for timestamp, value in dividends.items():
                if isinstance(timestamp, datetime):
                    event_date = timestamp.date()
                elif isinstance(timestamp, (int, float)):
                    event_date = datetime.fromtimestamp(timestamp / 1000).date()
                else:
                    warnings.append("Um registro de dividendos do Yahoo Finance tinha uma data inválida.")
                    continue
                try:
                    amount = float(value)
                except (TypeError, ValueError):
                    warnings.append("Um registro de dividendos do Yahoo Finance tinha um valor inválido.")
                    continue
                if not isfinite(amount) or amount < 0:
                    warnings.append("Um registro de dividendos do Yahoo Finance tinha um valor inválido.")
                    continue
                event_count += 1
                if event_date <= date.today():
                    history[event_date.year] = history.get(event_date.year, 0.0) + amount

        warnings.append(
            "O Yahoo Finance fornece datas ex-dividendo, não datas de pagamento; "
            "o histórico anual usa essas datas e os dividendos pagos nos últimos 12 meses não estão disponíveis."
        )
        raw_yield = info.get("dividendYield")
        yield_value = self._normalize_yield(raw_yield)
        if raw_yield is not None and yield_value is None:
            warnings.append(
                "O Dividend Yield retornado pelo Yahoo Finance foi ignorado por conter valor inválido."
            )

        return AssetData(
            ticker=ticker,
            empresa=self._normalize_text(
                info.get("longName") or info.get("shortName"),
                ticker,
            ),
            preco_atual=float(price),
            dividend_yield=yield_value,
            dividendos_historicos=history,
            fonte="Yahoo Finance",
            avisos=tuple(warnings),
            eventos_encontrados=event_count,
        )

    def _aggregate_dividends(self, raw_history) -> dict[int, float]:
        history, _, _, _ = self._parse_dividends(raw_history)
        return history

    def _parse_dividends(
        self, raw_history
    ) -> tuple[dict[int, float], list[str], tuple[DividendPayment, ...] | None, int]:
        aggregated: dict[int, float] = {}
        warnings: list[str] = []
        payments: list[DividendPayment] = []
        event_count = 0
        payment_dates_complete = True
        if isinstance(raw_history, dict):
            raw_history = raw_history.get("cashDividends") or []
        if not isinstance(raw_history, list):
            return {}, ["O histórico de dividendos da BRAPI está malformado."], None, 0
        for item in raw_history:
            if not isinstance(item, dict):
                warnings.append("Um registro de dividendos da BRAPI foi ignorado por estar malformado.")
                payment_dates_complete = False
                continue
            value = next(
                (item[key] for key in ("value", "amount", "cashAmount", "rate") if item.get(key) is not None),
                None,
            )
            date_value = (
                item.get("paymentDate") or item.get("date") or item.get("exDate")
                or item.get("lastDatePrior") or item.get("label")
            )
            if value is None or date_value is None:
                warnings.append("Um registro de dividendos da BRAPI não continha valor ou data.")
                payment_dates_complete = False
                continue
            try:
                event_date = date.fromisoformat(str(date_value)[:10])
                amount = float(value)
                if not isfinite(amount) or amount < 0:
                    warnings.append("Um registro de dividendos da BRAPI continha valor ou data inválidos.")
                    payment_dates_complete = False
                    continue
                event_count += 1
                if event_date <= date.today():
                    aggregated[event_date.year] = aggregated.get(event_date.year, 0.0) + amount
                if item.get("paymentDate") and not item.get("paymentDateIsDeadline"):
                    payments.append(DividendPayment(event_date, amount))
                else:
                    payment_dates_complete = False
                    warnings.append(
                        "Alguns registros anuais usam data ex ou prazo de pagamento em vez de uma data de pagamento confirmada."
                    )
            except (TypeError, ValueError):
                warnings.append("Um registro de dividendos da BRAPI continha valor ou data inválidos.")
                payment_dates_complete = False
                continue
        if not payment_dates_complete:
            warnings.append(
                "O LTM inclui apenas pagamentos com data informada; registros sem data válida "
                "foram omitidos e o valor pode estar incompleto."
            )
        return aggregated, list(dict.fromkeys(warnings)), tuple(payments) if payments else None, event_count

    @staticmethod
    def _normalize_yield(value) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if not isfinite(result) or result < 0:
            return None
        return result * 100 if result <= 1 else result

    @staticmethod
    def _normalize_text(value: str | None, fallback: str) -> str:
        text = (value or fallback).strip()
        if "Ã" in text:
            try:
                text = text.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return text
