from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_pagina_como_funciona():
    response = client.get("/como-funciona")
    assert response.status_code == 200
    assert "Como funciona e fontes dos dados" in response.text
    for text in (
        "O caminho de um número",
        "Quais informações são coletadas",
        "Fontes dos dados",
        "BRAPI",
        "Yahoo Finance",
        "COTAHIST",
        "O que a aplicação não faz",
        "Perguntas frequentes",
    ):
        assert text in response.text
    assert 'href="/como-funciona" aria-current="page"' in response.text


def test_navegacao_das_paginas_inclui_como_funciona():
    for path in ("/", "/cash-yield", "/gerarlista"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'href="/como-funciona"' in response.text
