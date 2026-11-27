"""Contratos de dados persistidos no Firestore.

Os dicionários são gravados diretamente; ``TypedDict`` documenta o formato sem
custo de conversão. As configurações e resultados continuam dataclasses
congeladas.
"""

from typing import Literal, TypedDict

TipoProvento = Literal["DIVIDENDO", "JCP", "RENDIMENTO", "OUTRO"]


class Quote(TypedDict):
    data: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class EventoProvento(TypedDict):
    evento_id: str
    ticker: str
    tipo_provento: TipoProvento
    data_com: str
    data_ex: str | None
    data_pagamento: str | None
    valor_bruto: float
    fonte: str
