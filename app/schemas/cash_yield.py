from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class YearYieldResponse(BaseModel):
    ano: int
    dividendos: float
    y1: float


class CriterioResponse(BaseModel):
    nome: str
    status: Literal["aprovado", "atencao", "reprovado"]
    valor: str | None
    texto: str


class CashYieldItem(BaseModel):
    posicao: int
    ticker: str
    empresa: str
    preco_atual: float
    y1: float
    y1_minimo: float
    anos: list[YearYieldResponse]
    fonte: str
    veredito: Literal["aprovada", "atencao"]
    criterios: list[CriterioResponse]
    alertas: list[str]


class CashYieldResponse(BaseModel):
    status: Literal["vazio", "calculando", "pronto"]
    processados: int
    total: int
    atualizado_em: datetime | None
    total_analisados: int | None
    total_qualificados: int | None
    total_reprovados_fundamentos: int | None
    itens: list[CashYieldItem]
    avisos: list[str]


class PrecoTetoResponse(BaseModel):
    taxa: float
    dpa_ltm: float | None
    preco_teto_ltm: float | None
    margem_ltm: float | None
    dpa_media_5anos: float
    preco_teto_media_5anos: float
    margem_media_5anos: float
    cenario_conservador: float
    observacoes: list[str]


class AnaliseResponse(BaseModel):
    ticker: str
    empresa: str
    veredito: Literal["aprovada", "atencao", "reprovada"]
    resumo: str
    preco_atual: float
    preco_teto: PrecoTetoResponse
    criterios_principais: list[CriterioResponse]
    saude_financeira: list[CriterioResponse]
    riscos: list[str]
