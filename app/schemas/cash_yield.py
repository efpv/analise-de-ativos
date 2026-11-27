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
    preco_teto: float
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


class DpaAnoResponse(BaseModel):
    ano: int
    dpa: float


class PrecoTetoResponse(BaseModel):
    taxa: float
    dpa_anos: list[DpaAnoResponse]
    dpa_media_3anos: float
    preco_teto_3anos: float
    margem_3anos: float
    dpa_ltm: float | None
    preco_teto_ltm: float | None
    margem_ltm: float | None
    preco_teto_conservador: float
    margem_conservador: float
    observacoes: list[str]


class NoticiaResponse(BaseModel):
    titulo: str
    resumo: str | None
    link: str
    fonte: str
    publicado_em: datetime | None


class NoticiasResponse(BaseModel):
    itens: list[NoticiaResponse]
    avisos: list[str]


class AnaliseResponse(BaseModel):
    ticker: str
    empresa: str
    veredito: Literal["aprovada", "atencao", "reprovada"]
    resumo: str
    preco_atual: float
    perfil: str
    preco_teto: PrecoTetoResponse
    criterios_principais: list[CriterioResponse]
    saude_financeira: list[CriterioResponse]
    riscos: list[str]
