from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class YearYield:
    ano: int
    dividendos: float
    y1: float


@dataclass(frozen=True)
class CashYieldCandidate:
    ticker: str
    empresa: str
    preco_atual: float
    y1: float
    y1_minimo: float
    anos: tuple[YearYield, ...]
    fonte: str


@dataclass(frozen=True)
class CashYieldSnapshot:
    atualizado_em: datetime
    total_analisados: int
    total_qualificados: int
    candidatos: tuple[CashYieldCandidate, ...]
    avisos: tuple[str, ...] = ()
