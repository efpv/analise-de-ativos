from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.valuation import DividendPeriod


class DividendHistory(BaseModel):
    ano: int
    valor: float
    situacao: Literal["parcial", "encerrado", "sem_registro"]


class DividendSummary(BaseModel):
    anos_analisados: int | None
    maior_anual: float | None
    menor_anual: float | None
    crescimento_medio: float | None


class ProfilePrices(BaseModel):
    agressivo: float
    moderado: float
    conservador: float


class DividendPaymentResponse(BaseModel):
    data: date
    valor: float


class ValuationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ticker: str
    empresa: str
    preco_atual: float
    dividend_yield: float | None
    dividendos_historicos: list[DividendHistory]
    dividendos_medios: float
    taxa_bazin: float
    preco_justo: float
    margem_seguranca: float
    status: str
    fonte: str
    data_consulta: datetime
    avisos: list[str]
    setor: str | None
    ativos_comparaveis: list[str]
    periodo: DividendPeriod
    dividendos_ltm: float | None
    pagamentos_ltm: list[DividendPaymentResponse] | None
    ano_dividend_yield: int
    dividendos_dividend_yield: float
    eventos_encontrados: int | None
    resumo_dividendos: DividendSummary
    precos_perfil: ProfilePrices


class RankingResponse(BaseModel):
    itens: list[ValuationResponse]
    ordem: str
    avisos: list[str]


class ComparisonResponse(BaseModel):
    itens: list[ValuationResponse]
    avisos: list[str] = Field(default_factory=list)
