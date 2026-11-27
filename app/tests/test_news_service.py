from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.schemas.cash_yield import NoticiasResponse
from app.services import news_service as news_module
from app.services.news_service import NewsService, _category_feeds, load_feeds

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


def test_feeds_por_categoria_filtram_lista(tmp_path):
    feeds = load_feeds(write_feeds(tmp_path))
    selected = _category_feeds(["Economia", "Mercado Financeiro"], feeds)
    assert [url for _, url in selected] == [
        "https://news.google.com/rss/search?q=B3+bolsa&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://example.com/mercado.rss",
        "https://example.com/economia.rss",
    ]


def test_busca_por_categoria_deduplica_ordena_e_usa_cache(tmp_path):
    path = write_feeds(tmp_path)
    service = NewsService(path)
    calls = []

    def fake_fetch(client, url):
        calls.append(url)
        if "mercado.rss" in url:
            return MARKET_RSS.encode("utf-8")
        if "economia.rss" in url:
            return GOOGLE_RSS.replace("AAAA3 sobe após resultado", "Economia noticia").encode("utf-8")
        raise ValueError("feed indisponível")

    service._fetch_feed = fake_fetch
    result = service.get_by_categories(["Mercado Financeiro", "Economia"])

    titles = [item.titulo for item in result.itens]
    assert "Empresa AAAA3 no mercado" in titles
    assert titles.count("Empresa AAAA3 no mercado") == 1
    assert result.itens[0].categoria in {"Mercado Financeiro", "Economia"}

    first_call_count = len(calls)
    service.get_by_categories(["Mercado Financeiro", "Economia"])
    assert len(calls) == first_call_count


def test_sem_feeds_retorna_aviso(tmp_path, monkeypatch):
    monkeypatch.setattr(news_module, "load_feeds", lambda path=tmp_path / "feeds.txt": ())
    result = NewsService(tmp_path / "feeds.txt").get_by_categories(["Economia"])
    assert result.itens == []
    assert result.avisos == ["Nenhuma lista de feeds RSS foi encontrada."]



