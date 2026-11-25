from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class YearYieldResponse(BaseModel):
    ano: int
    dividendos: float
    y1: float


class CashYieldItem(BaseModel):
    posicao: int
    ticker: str
    empresa: str
    preco_atual: float
    y1: float
    y1_minimo: float
    anos: list[YearYieldResponse]
    fonte: str


class CashYieldResponse(BaseModel):
    status: Literal["vazio", "calculando", "pronto"]
    processados: int
    total: int
    atualizado_em: datetime | None
    total_analisados: int | None
    total_qualificados: int | None
    itens: list[CashYieldItem]
    avisos: list[str]
