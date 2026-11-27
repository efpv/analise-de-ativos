import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.models.cash_yield import CashYieldCandidate, CashYieldSnapshot, Criterio, YearYield
from app.models.valuation import AssetData
from app.services.bazin_analysis import assess_fundamentals, dividend_alerts, verdict
from app.repositories.asset_cache_repository import AssetCacheRepository
from app.repositories.firestore_store import FirestoreAssetCache, FirestoreStateStore
from app.services.ticker_service import TickerService

logger = logging.getLogger(__name__)

MIN_Y1 = 6.0
YEARS_REQUIRED = 3
CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "ativos_b3.json"
CATALOG_TYPES = ("STOCK", "UNIT")
DIVIDENDS_TTL = timedelta(days=30)
PRICE_TTL = timedelta(days=1)
STALE_SCAN = timedelta(minutes=10)
PROGRESS_EVERY = 10


def evaluate(asset: AssetData, today: date | None = None) -> CashYieldCandidate | None:
    """Aplica a pré-qualificação e a qualificação quantitativa do cash-yield.

    O y1 de cada um dos três últimos anos civis encerrados usa o preço atual, pois a
    fonte não fornece o preço histórico da época de cada pagamento.
    """
    today = today or date.today()
    if asset.preco_atual <= 0:
        return None
    years = []
    for year in range(today.year - YEARS_REQUIRED, today.year):
        dividends = asset.dividendos_historicos.get(year, 0.0)
        y1 = dividends / asset.preco_atual * 100
        if dividends <= 0 or y1 < MIN_Y1:
            return None
        years.append(YearYield(ano=year, dividendos=dividends, y1=y1))
    criteria = assess_fundamentals(asset.fundamentos, asset.empresa)
    return CashYieldCandidate(
        ticker=asset.ticker,
        empresa=asset.empresa,
        preco_atual=asset.preco_atual,
        y1=years[-1].y1,
        y1_minimo=min(item.y1 for item in years),
        anos=tuple(years),
        fonte=asset.fonte,
        veredito=verdict(criteria),
        criterios=tuple(criteria),
        alertas=tuple(dividend_alerts(asset.dividendos_historicos, today)),
    )


def rank(candidates: list[CashYieldCandidate]) -> list[CashYieldCandidate]:
    order = {"aprovada": 0, "atencao": 1}
    return sorted(candidates, key=lambda item: (order.get(item.veredito, 2), -item.y1_minimo, -item.y1, item.ticker))


def catalog_tickers() -> list[str]:
    with CATALOG_PATH.open(encoding="utf-8") as file:
        return sorted({
            item["ticker"] for item in json.load(file)
            if item.get("type") in CATALOG_TYPES and not item["ticker"].endswith("F")
        })


class CashYieldService:
    def __init__(
        self, ticker_service: TickerService | None = None, cache_path: str | None = None,
        asset_cache: AssetCacheRepository | FirestoreAssetCache | None = None,
        state_store: FirestoreStateStore | None = None,
    ) -> None:
        self.ticker_service = ticker_service or TickerService()
        use_firestore = settings.storage_backend == "firestore"
        self._asset_cache = asset_cache or (FirestoreAssetCache() if use_firestore else None)
        self._state_store = state_store or (FirestoreStateStore() if use_firestore else None)
        self._cache_path = cache_path
        self._lock = threading.Lock()
        self._running = False
        self._processed = 0
        self._total = 0
        self._snapshot: CashYieldSnapshot | None = None
        self._loaded = False

    @property
    def cache_path(self) -> Path:
        return Path(self._cache_path or settings.cash_yield_cache_path)

    @property
    def asset_cache(self) -> AssetCacheRepository:
        if self._asset_cache is None:
            self._asset_cache = AssetCacheRepository()
        return self._asset_cache

    def load_asset(self, ticker: str) -> AssetData:
        """Usa os dados salvos quando recentes; consulta a fonte apenas para o que estiver vencido."""
        now = datetime.now(timezone.utc)
        cached = self.asset_cache.get(ticker)
        if cached:
            age = now - cached.dividendos_em
            if not cached.encontrado:
                if age < PRICE_TTL:
                    raise LookupError("Ativo não encontrado.")
            elif age < DIVIDENDS_TTL and cached.dividendos_em.year == now.year:
                if cached.preco_em and now - cached.preco_em < PRICE_TTL:
                    return cached.asset
                price = self.ticker_service.get_price(ticker)
                if price:
                    self.asset_cache.update_price(ticker, price, now)
                    return replace(cached.asset, preco_atual=price)
        try:
            asset = self.ticker_service.get_asset(ticker)
        except LookupError:
            self.asset_cache.save_missing(ticker, now)
            raise
        self.asset_cache.save_asset(asset, now)
        return asset

    def with_fundamentals(self, asset: AssetData) -> AssetData:
        """Busca os indicadores de balanço apenas para ativos que já passaram no y1."""
        if asset.fundamentos is not None and (asset.fundamentos.setor or asset.fundamentos.industria):
            return asset
        fundamentals = self.ticker_service.get_fundamentals(asset.ticker)
        if fundamentals is None:
            return asset
        self.asset_cache.update_fundamentals(asset.ticker, fundamentals)
        return replace(asset, fundamentos=fundamentals)

    def _remote_progress(self) -> tuple[bool, int, int]:
        data = self._state_store.get_progress()
        if not data:
            return False, 0, 0
        fresh = datetime.now(timezone.utc) - datetime.fromisoformat(data["atualizado_em"]) < STALE_SCAN
        return bool(data["executando"]) and fresh, data["processados"], data["total"]

    def _save_progress(self, running: bool, processed: int, total: int) -> None:
        if self._state_store:
            self._state_store.set_progress({
                "executando": running, "processados": processed, "total": total,
                "atualizado_em": datetime.now(timezone.utc).isoformat(),
            })

    def status(self) -> tuple[bool, int, int, CashYieldSnapshot | None]:
        if self._state_store:
            running, processed, total = self._remote_progress()
            data = self._state_store.get_snapshot()
            return running, processed, total, self._snapshot_from_dict(data) if data else None
        with self._lock:
            if not self._loaded:
                self._snapshot = self._read_cache()
                self._loaded = True
            return self._running, self._processed, self._total, self._snapshot

    def start(
        self, tickers: list[str] | None = None, wait: bool = False, escopo: str = "catalogo"
    ) -> bool:
        if self._state_store and self._remote_progress()[0]:
            return False
        with self._lock:
            if self._running:
                return False
            universe = tickers if tickers is not None else catalog_tickers()
            self._running = True
            self._processed = 0
            self._total = len(universe)
        self._save_progress(True, 0, len(universe))
        worker = threading.Thread(target=self._scan, args=(universe, escopo), daemon=True)
        worker.start()
        if wait:
            worker.join()
        return True

    def _scan(self, tickers: list[str], escopo: str = "catalogo") -> None:
        candidates: list[CashYieldCandidate] = []
        rejected: list[str] = []
        failures = 0

        def process(ticker: str) -> None:
            nonlocal failures
            try:
                asset = self.load_asset(ticker)
                if evaluate(asset):
                    candidate = evaluate(self.with_fundamentals(asset))
                    with self._lock:
                        if candidate.veredito == "reprovada":
                            rejected.append(ticker)
                        else:
                            candidates.append(candidate)
            except Exception as exc:
                if not isinstance(exc, (LookupError, ValueError)):
                    logger.exception("Falha inesperada na triagem cash-yield: ticker=%s", ticker)
                with self._lock:
                    failures += 1
            finally:
                with self._lock:
                    self._processed += 1
                    processed = self._processed
                if processed % PROGRESS_EVERY == 0:
                    self._save_progress(True, processed, len(tickers))

        try:
            with ThreadPoolExecutor(max_workers=max(1, settings.cash_yield_workers)) as executor:
                list(executor.map(process, tickers))
            warnings = tuple(filter(None, (
                f"Lista piloto: análise limitada a {len(tickers)} ativo(s) de validação."
                if escopo == "piloto" else "",
                f"{failures} ativo(s) foram ignorados por falta de dados nas fontes consultadas." if failures else "",
                f"{len(rejected)} ativo(s) com y1 aprovado foram excluídos por endividamento, liquidez ou balanço."
                if rejected else "",
            )))
            snapshot = CashYieldSnapshot(
                atualizado_em=datetime.now(timezone.utc),
                total_analisados=len(tickers) - failures,
                total_qualificados=len(candidates),
                total_reprovados_fundamentos=len(rejected),
                candidatos=tuple(rank(candidates)),
                avisos=warnings,
            )
            with self._lock:
                self._snapshot = snapshot
                self._loaded = True
            self._write_cache(snapshot)
        finally:
            with self._lock:
                self._running = False
                processed = self._processed
            self._save_progress(False, processed, len(tickers))

    @staticmethod
    def _snapshot_from_dict(data: dict) -> CashYieldSnapshot:
        return CashYieldSnapshot(
            atualizado_em=datetime.fromisoformat(data["atualizado_em"]),
            total_analisados=data["total_analisados"],
            total_qualificados=data["total_qualificados"],
            candidatos=tuple(
                CashYieldCandidate(**{
                    **item,
                    "anos": tuple(YearYield(**year) for year in item["anos"]),
                    "criterios": tuple(Criterio(**criterion) for criterion in item.get("criterios", ())),
                    "alertas": tuple(item.get("alertas", ())),
                })
                for item in data["candidatos"]
            ),
            avisos=tuple(data.get("avisos", ())),
            total_reprovados_fundamentos=data.get("total_reprovados_fundamentos", 0),
        )

    def _read_cache(self) -> CashYieldSnapshot | None:
        try:
            return self._snapshot_from_dict(json.loads(self.cache_path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Cache cash-yield inválido; será ignorado.")
            return None

    def _write_cache(self, snapshot: CashYieldSnapshot) -> None:
        data = asdict(snapshot)
        data["atualizado_em"] = snapshot.atualizado_em.isoformat()
        if self._state_store:
            self._state_store.set_snapshot(data)
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.warning("Não foi possível gravar o cache cash-yield.")
