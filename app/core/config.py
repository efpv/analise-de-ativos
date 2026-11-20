from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    bazin_rate: float = float(os.getenv("BAZIN_RATE", "0.06"))
    database_path: str = os.getenv("DATABASE_PATH", "data/valuation_history.sqlite")
    request_timeout: float = 4.0
    brapi_api_key: str = os.getenv("BRAPI_API_KEY", "")
    ranking_enabled: bool = os.getenv("ENABLE_RANKING", "false").strip().lower() == "true"


settings = Settings()
