from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.schemas.cash_yield import NoticiaResponse, NoticiasResponse


from types import SimpleNamespace


def test_home_page_renderiza_filtros_de_noticias(monkeypatch):
    monkeypatch.setattr(routes, "settings", SimpleNamespace(ranking_enabled=False))
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Radar de notícias" in response.text
    for category in [
        "Política", "Economia", "Mercado Financeiro",
        "Internacional (Economia, Mercados e Geral)", "Criptomoedas", "Tecnologia e IA",
    ]:
        assert category in response.text
    assert 'id="news-list"' in response.text


def test_api_news_filtra_categorias(monkeypatch):
    called = {}

    class FakeNewsService:
        def get_by_categories(self, categories):
            called["categories"] = categories
            return NoticiasResponse(itens=[NoticiaResponse(
                titulo="Manchete", resumo="Resumo", link="https://example.com/n",
                fonte="Fonte", publicado_em=None, categoria=categories[0],
            )], avisos=[])

    monkeypatch.setattr(routes, "news_service", FakeNewsService())
    response = TestClient(app).get("/api/v1/news?categorias=Economia&categorias=Tecnologia%20e%20IA")

    assert response.status_code == 200
    assert called["categories"] == ["Economia", "Tecnologia e IA"]
    assert response.json()["itens"][0]["categoria"] == "Economia"


def test_api_news_rejeita_categoria_invalida():
    response = TestClient(app).get("/api/v1/news?categorias=Esportes")
    assert response.status_code == 400
    assert "Categoria inválida" in response.json()["detail"]