from pydantic import BaseModel


class QuoteResponse(BaseModel):
    data: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class EventoResponse(BaseModel):
    evento_id: str
    ticker: str
    tipo_provento: str
    data_com: str
    data_ex: str | None
    data_pagamento: str | None
    valor_bruto: float
    fonte: str


class MarketDataResponse(BaseModel):
    ticker: str
    inicio: str | None
    fim: str | None
    cotacoes: list[QuoteResponse]
    proventos: list[EventoResponse]
    avisos: list[str]
