from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.schemas.cash_yield import NoticiasResponse
from app.services import news_service as news_module
from app.services.news_service import NewsService, _ordered_feeds, load_feeds

FEEDS = """Mercado Financeiro
https://news.google.com/rss/search?q=B3+bolsa&hl=pt-BR&gl=BR&ceid=BR:pt-419
https://example.com/mercado.rss
Economia
https://example.com/economia.rss
Tecnologia
https://example.com/tech.rss
"""

GOOGLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item>
    <title>AAAA3 sobe após resultado</title>
    <link>https://news.example.com/aaaa3-resultado</link>
    <description><![CDATA[<p>Banco AAAA3 divulgou lucro acima do esperado.</p>]]></description>
    <pubDate>Mon, 24 Nov 2025 12:00:00 GMT</pubDate>
    <source>Google Notícias</source>
  </item>
  <item>
    <title>Empresa AAAA3 anuncia dividendos</title>
    <link>https://news.example.com/empresa-aaaa3-dividendos</link>
    <description>Dividendos aprovados.</description>
    <pubDate>Tue, 25 Nov 2025 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Outro ativo qualquer</title>
    <link>https://news.example.com/outro</link>
    <description>Sem menção ao ticker.</description>
    <pubDate>Wed, 26 Nov 2025 12:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""

MARKET_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item>
    <title>Empresa AAAA3 no mercado</title>
    <link>https://example.com/mercado-aaaa3</link>
    <description>Notícia repetida do portal.</description>
    <pubDate>Mon, 24 Nov 2025 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Empresa AAAA3 no mercado</title>
    <link>https://example.com/mercado-aaaa3</link>
    <description>Mesma notícia, outro feed.</description>
    <pubDate>Mon, 24 Nov 2025 12:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


def write_feeds(tmp_path):
    path = tmp_path / "feeds.txt"
    path.write_text(FEEDS, encoding="utf-8")
    return path


def test_lista_de_feeds_gera_busca_google_news_para_o_ticker(tmp_path):
    feeds = load_feeds(write_feeds(tmp_path))
    ordered = _ordered_feeds("AAAA3", "Empresa AAAA3", feeds)

    assert len(feeds) == 4
    assert "news.google.com" in ordered[0][1]
    assert "AAAA3" in ordered[0][1]
    assert "Empresa+AAAA3" in ordered[0][1]
    assert [url for _, url in ordered[1:]] == [
        "https://example.com/mercado.rss",
        "https://example.com/economia.rss",
        "https://example.com/tech.rss",
    ]
    assert "B3+bolsa" not in ordered[0][1]


def test_busca_filtra_por_ticker_ou_empresa_deduplica_e_ordena(tmp_path):
    path = write_feeds(tmp_path)
    service = NewsService(path)
    calls = []

    def fake_fetch(client, url):
        calls.append(url)
        if "news.google.com" in url:
            assert "AAAA3" in url
            return GOOGLE_RSS.encode("utf-8")
        if "mercado.rss" in url:
            return MARKET_RSS.encode("utf-8")
        raise ValueError("feed indisponível")

    service._fetch_feed = fake_fetch
    result = service.get_news("aaaa3", "Empresa AAAA3")

    titles = [item.titulo for item in result.itens]
    assert set(titles[:3]) == {
        "Empresa AAAA3 anuncia dividendos",
        "AAAA3 sobe após resultado",
        "Empresa AAAA3 no mercado",
    }
    assert "Outro ativo qualquer" not in titles
    by_title = {item.titulo: item for item in result.itens}
    assert by_title["Empresa AAAA3 anuncia dividendos"].publicado_em.day == 25
    assert "Banco AAAA3" in by_title["AAAA3 sobe após resultado"].resumo
    assert by_title["AAAA3 sobe após resultado"].fonte == "Google Notícias"
    assert any("2 fonte(s)" in text for text in result.avisos)

    first_call_count = len(calls)
    service.get_news("AAAA3", "Empresa AAAA3")
    assert len(calls) == first_call_count


def test_sem_feeds_retorna_aviso(tmp_path, monkeypatch):
    monkeypatch.setattr(news_module, "load_feeds", lambda path: ())
    result = NewsService(tmp_path / "feeds.txt").get_news("AAAA3")
    assert result.itens == []
    assert result.avisos == ["Nenhuma lista de feeds RSS foi encontrada."]


def test_endpoint_de_noticias_valida_ticker_e_delega(monkeypatch):
    called = {}

    class FakeNewsService:
        def get_news(self, ticker, empresa):
            called.update(ticker=ticker, empresa=empresa)
            return NoticiasResponse(itens=[], avisos=[])

    monkeypatch.setattr(routes, "news_service", FakeNewsService())
    client = TestClient(app)
    assert client.get("/api/v1/cash-yield/invalido/noticias").status_code == 400

    response = client.get("/api/v1/cash-yield/aaaa3/noticias?empresa=Empresa%20AAAA3")
    assert response.status_code == 200
    assert response.json() == {"itens": [], "avisos": []}
    assert called == {"ticker": "AAAA3", "empresa": "Empresa AAAA3"}


def test_empresa_e_limitada_no_endpoint(monkeypatch):
    called = {}

    class FakeNewsService:
        def get_news(self, ticker, empresa):
            called["empresa"] = empresa
            return NoticiasResponse(itens=[], avisos=[])

    monkeypatch.setattr(routes, "news_service", FakeNewsService())
    response = TestClient(app).get(f"/api/v1/cash-yield/AAAA3/noticias?empresa={'x' * 200}")
    assert response.status_code == 422
    assert "empresa" not in called


@pytest.mark.parametrize("value", [None, ""])
def test_endpoint_sem_empresa(monkeypatch, value):
    monkeypatch.setattr(routes.news_service, "get_news", lambda ticker, empresa: NoticiasResponse(itens=[], avisos=[]))
    response = TestClient(app).get(
        "/api/v1/cash-yield/AAAA3/noticias" if value is None else "/api/v1/cash-yield/AAAA3/noticias?empresa="
    )
    assert response.status_code == 200
    assert response.json() == {"itens": [], "avisos": []}
