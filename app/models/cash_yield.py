from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class YearYield:
    ano: int
    dividendos: float
    y1: float


@dataclass(frozen=True)
class Criterio:
    nome: str
    status: str
    valor: str | None
    texto: str


@dataclass(frozen=True)
class CashYieldCandidate:
    ticker: str
    empresa: str
    preco_atual: float
    y1: float
    y1_minimo: float
    anos: tuple[YearYield, ...]
    fonte: str
    veredito: str = "aprovada"
    criterios: tuple[Criterio, ...] = ()
    alertas: tuple[str, ...] = ()


@dataclass(frozen=True)
class CashYieldSnapshot:
    atualizado_em: datetime
    total_analisados: int
    total_qualificados: int
    candidatos: tuple[CashYieldCandidate, ...]
    avisos: tuple[str, ...] = ()
    total_reprovados_fundamentos: int = 0
