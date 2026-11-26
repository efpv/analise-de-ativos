from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


DividendPeriod = Literal["ltm", "3anos", "5anos", "todos"]


@dataclass(frozen=True)
class DividendPayment:
    data: date
    valor: float


@dataclass(frozen=True)
class Fundamentals:
    divida_liquida: float | None = None
    ebitda: float | None = None
    liquidez_corrente: float | None = None
    p_vp: float | None = None
    roe: float | None = None
    volume_financeiro: float | None = None
    fluxo_caixa_operacional: float | None = None
    fluxo_caixa_livre: float | None = None


@dataclass(frozen=True)
class AssetData:
    ticker: str
    empresa: str
    preco_atual: float
    dividend_yield: float | None
    dividendos_historicos: dict[int, float]
    fonte: str = "Desconhecida"
    avisos: tuple[str, ...] = ()
    pagamentos: tuple[DividendPayment, ...] | None = None
    eventos_encontrados: int | None = None
    fundamentos: Fundamentals | None = None


@dataclass(frozen=True)
class Valuation:
    ticker: str
    empresa: str
    preco_atual: float
    dividend_yield: float
    dividendos_historicos: dict[int, float]
    dividendos_medios: float
    taxa_bazin: float
    preco_justo: float
    margem_seguranca: float
    status: str
    fonte: str
    data_consulta: datetime
    avisos: tuple[str, ...]
    periodo: DividendPeriod
    dividendos_ltm: float | None
    pagamentos_ltm: tuple[DividendPayment, ...] | None
    ano_dividend_yield: int
    dividendos_dividend_yield: float
    eventos_encontrados: int | None
    anos_registrados: frozenset[int]


@dataclass(frozen=True)
class Consultation:
    ticker: str
    data_consulta: date
    preco_atual: float
    preco_justo: float
