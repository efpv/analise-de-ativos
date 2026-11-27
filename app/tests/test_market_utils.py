import json
import logging

import pytest

from src.utils.logging import JsonFormatter
from src.utils.retry import retry


def test_json_formatter_inclui_campos_extras():
    record = logging.LogRecord(
        "teste", logging.INFO, __file__, 1, "mensagem", None, None
    )
    record.__dict__["ticker"] = "ITUB4"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "teste"
    assert payload["message"] == "mensagem"
    assert payload["ticker"] == "ITUB4"
    assert "timestamp" in payload


def test_json_formatter_inclui_excecao():
    try:
        raise RuntimeError("falha")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "teste", logging.ERROR, __file__, 1, "erro", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "exception" in payload
    assert "RuntimeError" in payload["exception"]


def test_retry_nao_loga_mensagem_da_excecao(monkeypatch, caplog):
    from src.utils import retry as retry_module

    monkeypatch.setattr(retry_module.time, "sleep", lambda _: None)

    class Transitoria(Exception):
        pass

    def falha():
        raise Transitoria("segredo")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(Transitoria):
            retry(
                falha,
                attempts=2,
                base_delay=0.001,
                retryable=(Transitoria,),
                logger=logging.getLogger("teste"),
                context={"ticker": "ITUB4"},
            )

    assert "segredo" not in caplog.text
    assert caplog.records
    record = caplog.records[0]
    assert "segredo" not in str(record.__dict__)
    assert record.ticker == "ITUB4"
    assert record.tipo_erro == "Transitoria"


def test_retry_retorna_sucesso_sem_repetir(monkeypatch):
    chamadas = []

    def sucesso():
        chamadas.append(1)
        return "ok"

    monkeypatch.setattr(
        "src.utils.retry.time.sleep",
        lambda _: pytest.fail("não deve dormir"),
    )
    assert retry(
        sucesso, attempts=3, base_delay=1.0, retryable=(RuntimeError,)
    ) == "ok"
    assert len(chamadas) == 1


def test_retry_propaga_erro_nao_retryable_sem_repetir():
    chamadas = []

    def falha():
        chamadas.append(1)
        raise ValueError("permanente")

    with pytest.raises(ValueError, match="permanente"):
        retry(falha, attempts=3, base_delay=0.0, retryable=(RuntimeError,))
    assert len(chamadas) == 1

