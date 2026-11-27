"""Normalização e validação de tickers da B3.

Mesmo padrão e mesma mensagem de ``app.services.ticker_service.TickerService``
(RF-12). A unificação das duas regexes fica para a v2.
"""

import re

TICKER_PATTERN = re.compile(r"[A-Z0-9]{4}[0-9]{1,2}[A-Z]?F?")
_TICKER_ERROR = "Informe um ticker válido da B3, por exemplo BBAS3."


def normalize_ticker(value: str) -> str:
    """Retorna o ticker em maiúsculas ou levanta ``ValueError``."""
    normalized = str(value).strip().upper()
    if not TICKER_PATTERN.fullmatch(normalized):
        raise ValueError(_TICKER_ERROR)
    return normalized
