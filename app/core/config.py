from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    bazin_rate: float = float(os.getenv("BAZIN_RATE", "0.06"))
    database_path: str = os.getenv("DATABASE_PATH", "data/valuation_history.sqlite")
    request_timeout: float = 4.0
    brapi_api_key: str = os.getenv("BRAPI_API_KEY", "")
    cash_yield_cache_path: str = os.getenv("CASH_YIELD_CACHE_PATH", "data/cash_yield_cache.json")
    cash_yield_workers: int = int(os.getenv("CASH_YIELD_WORKERS", "4"))
    storage_backend: str = os.getenv("STORAGE_BACKEND", "sqlite").strip().lower()
    firestore_project: str = os.getenv("FIRESTORE_PROJECT", "")
    firestore_prefix: str = os.getenv("FIRESTORE_PREFIX", "")
    ranking_enabled: bool = os.getenv("ENABLE_RANKING", "false").strip().lower() == "true"


settings = Settings()
