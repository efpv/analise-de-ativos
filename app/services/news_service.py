import html
import logging
import re
import threading
import unicodedata
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from app.schemas.cash_yield import NoticiaResponse, NoticiasResponse

logger = logging.getLogger(__name__)

FEEDS_PATH = Path(__file__).resolve().parents[2] / "listaRss.txt"
REQUEST_TIMEOUT = 3.0
FETCH_DEADLINE = 6.0
MAX_WORKERS = 12
CACHE_TTL = timedelta(minutes=15)
MAX_ITENS = 6
MAX_POR_FEED = 20
SUMMARY_LIMIT = 240
HTML_TAG = re.compile(r"<[^>]+>")
LEGAL_SUFFIXES = re.compile(
    r"\b(S\.?/?A\.?|S/?A|LTDA\.?|HOLDING|PARTICIPACOES|PARTICIPAÇÕES|COMPANHIA|CIA\.?)\b",
    re.IGNORECASE,
)
WEAK_KEYWORDS = {"banco", "brasil", "vale", "energia", "nacional", "geral", "americana"}
MARKET_CONTEXT = {
    "acoes", "acao", "b3", "bolsa", "dividendos", "dividendo", "lucro", "ibovespa",
    "mercado", "investidor", "pregao", "cotacao", "balanco", "resultado", "proventos",
    "ticker", "acionista", "papel", "papeis",
}
RELEVANT_CATEGORIES = {"mercado financeiro", "economia"}
HOME_CATEGORIES = (
    "Política",
    "Economia",
    "Mercado Financeiro",
    "Internacional (Economia, Mercados e Geral)",
    "Criptomoedas",
    "Tecnologia e IA",
)
HOME_CATEGORY_ALIASES = {category.casefold(): category for category in HOME_CATEGORIES}
USER_AGENT = "PrecoJustoBazin/1.0 (consulta de noticias por RSS)"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _clean(value: str | None) -> str:
    return " ".join(html.unescape(HTML_TAG.sub(" ", value or "")).split())


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").casefold()


def company_keywords(empresa: str) -> tuple[str, ...]:
    """Extrai palavras úteis do nome da empresa para busca e matching."""
    clean = LEGAL_SUFFIXES.sub(" ", _clean(empresa))
    clean = re.sub(r"[^A-Za-z0-9À-ÿ\s-]", " ", clean)
    tokens = []
    for raw in clean.split():
        token = _normalize(raw).strip("-")
        if len(token) < 4 or token in {"grupo"}:
            continue
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens[:3])


@lru_cache(maxsize=4)
def load_feeds(path: Path = FEEDS_PATH) -> tuple[tuple[str, str], ...]:
    """Lê o arquivo de listas RSS: linhas sem URL são categorias, linhas com URL são feeds."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Lista de feeds RSS indisponível: arquivo=%s", path.name)
        return ()
    feeds: list[tuple[str, str]] = []
    seen: set[str] = set()
    category = "Geral"
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith(("http://", "https://")):
            category = line[:80]
            continue
        parsed = urlparse(line)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or line in seen:
            continue
        seen.add(line)
        feeds.append((category, line))
    return tuple(feeds)


def _ticker_search_url(ticker: str, empresa: str, feeds: tuple[tuple[str, str], ...]) -> str | None:
    """Reaproveita um Google News RSS da lista, trocando apenas o termo buscado."""
    template = next(
        (
            url for _, url in feeds
            if urlparse(url).netloc.casefold().endswith("news.google.com")
            and dict(parse_qsl(urlparse(url).query)).get("q")
        ),
        None,
    )
    if not template:
        return None
    keywords = company_keywords(empresa)
    terms = [f'"{ticker}"']
    if empresa:
        terms.append(f'"{empresa}"')
    terms.extend(f'"{keyword}"' for keyword in keywords)
    query = f'({" OR ".join(dict.fromkeys(terms))})'
    if keywords:
        keyword_terms = " OR ".join(f'"{keyword}"' for keyword in keywords)
        query += f" ({keyword_terms} OR B3 OR ações OR acao OR bolsa)"
    else:
        query += " (B3 OR ações OR acao OR bolsa)"
    parsed = urlparse(template)
    params = [(key, query if key == "q" else value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunparse(parsed._replace(query=urlencode(params)))


def _category_feeds(categories: list[str] | None = None, feeds: tuple[tuple[str, str], ...] | None = None) -> list[tuple[str, str]]:
    feeds = feeds if feeds is not None else load_feeds()
    if not categories:
        return list(feeds)
    wanted = {category.casefold() for category in categories}
    return [(category, url) for category, url in feeds if category.casefold() in wanted]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _child_text(entry: ElementTree.Element, *names: str) -> str | None:
    for child in entry:
        if _local_name(child.tag) in names:
            return "".join(child.itertext())
    return None


def _child_link(entry: ElementTree.Element) -> str | None:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = child.get("href")
        if href:
            return href
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return None


def _has_market_context(haystack: str) -> bool:
    return any(token in haystack for token in MARKET_CONTEXT)


def _matches(text: str, ticker: str, empresa: str, category: str = "") -> bool:
    haystack = _normalize(text)
    if re.search(rf"(?<![a-z0-9]){re.escape(ticker.casefold())}(?![a-z0-9])", haystack):
        return True
    company = _normalize(empresa)
    if company and company in haystack:
        return True
    keywords = company_keywords(empresa)
    if not keywords:
        return False
    strong = [k for k in keywords if k not in WEAK_KEYWORDS]
    has_strong = any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", haystack) for k in strong)
    if has_strong:
        return True
    weak_hits = sum(1 for k in keywords if k in WEAK_KEYWORDS and re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", haystack))
    if weak_hits == 0:
        return False
    if category.casefold() in RELEVANT_CATEGORIES or category.casefold().startswith("notícias de "):
        return True
    return weak_hits >= 2 and _has_market_context(haystack)


class NewsService:
    """Busca notícias nos feeds RSS do arquivo, com cache curto e tolerância a falhas."""

    def __init__(
        self, feeds_path: Path = FEEDS_PATH, timeout: float = REQUEST_TIMEOUT,
        deadline: float = FETCH_DEADLINE, max_workers: int = MAX_WORKERS,
    ) -> None:
        self.feeds_path = Path(feeds_path)
        self.timeout = timeout
        self.deadline = deadline
        self.max_workers = max_workers
        self._cache: dict[tuple[str, str], tuple[datetime, NoticiasResponse]] = {}
        self._lock = threading.Lock()

    def _fetch_feed(self, client: httpx.Client, url: str) -> bytes:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.content

    def _parse_entries(
        self, payload: bytes, category: str, url: str, matcher=None
    ) -> list[NoticiaResponse]:
        root = ElementTree.fromstring(payload)
        source_feed = _clean(category) or urlparse(url).netloc
        found: list[NoticiaResponse] = []
        for entry in root.iter():
            if _local_name(entry.tag) not in {"item", "entry"}:
                continue
            title = _clean(_child_text(entry, "title"))
            link = _child_link(entry) or ""
            if not title or not link.startswith(("http://", "https://")):
                continue
            summary = _clean(_child_text(entry, "description", "summary", "content"))[:SUMMARY_LIMIT]
            source = _clean(_child_text(entry, "source")) or source_feed
            published = _parse_date(_child_text(entry, "pubdate", "published", "updated", "date"))
            if matcher and not matcher(f"{title} {summary}", category):
                continue
            found.append(NoticiaResponse(
                titulo=title, resumo=summary or None, link=link,
                fonte=source, publicado_em=published, categoria=category,
            ))
            if len(found) >= MAX_POR_FEED:
                break
        return found

    def _collect(self, feeds: list[tuple[str, str]], matcher=None, empty_message: str = "Nenhuma notícia encontrada.") -> NoticiasResponse:
        if not feeds:
            return NoticiasResponse(itens=[], avisos=["Nenhuma lista de feeds RSS foi encontrada."])
        items: list[NoticiaResponse] = []
        seen: set[str] = set()
        failures = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures: dict[Future[bytes], tuple[str, str]] = {
                    executor.submit(self._fetch_feed, client, url): (category, url)
                    for category, url in feeds
                }
                try:
                    for future in as_completed(futures, timeout=self.deadline):
                        category, url = futures[future]
                        try:
                            payload = future.result()
                            parsed = self._parse_entries(payload, category, url, matcher)
                        except Exception as exc:
                            failures += 1
                            logger.warning(
                                "Falha em feed RSS: host=%s tipo=%s",
                                urlparse(url).netloc, type(exc).__name__,
                                extra={"provider": "rss", "error_type": type(exc).__name__},
                            )
                            continue
                        for item in parsed:
                            key = item.link or _normalize(item.titulo)
                            if key in seen:
                                continue
                            seen.add(key)
                            items.append(item)
                except FutureTimeoutError:
                    pending = [url for future, (_, url) in futures.items() if not future.done()]
                    failures += len(pending)
                    logger.warning(
                        "Tempo limite na busca de notícias: fontes_pendentes=%s",
                        len(pending), extra={"provider": "rss"},
                    )
                    for future in futures:
                        future.cancel()
        items.sort(key=lambda item: item.publicado_em or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        warnings = []
        if failures:
            warnings.append(f"{failures} fonte(s) RSS não responderam; resultado parcial.")
        if not items:
            warnings.append(empty_message)
        return NoticiasResponse(itens=items[:MAX_ITENS], avisos=warnings)

    def get_by_categories(self, categories: list[str] | None = None) -> NoticiasResponse:
        selected = []
        for category in categories or []:
            resolved = HOME_CATEGORY_ALIASES.get(category.casefold())
            if resolved and resolved not in selected:
                selected.append(resolved)
        feeds = _category_feeds(selected or list(HOME_CATEGORIES), load_feeds(self.feeds_path))
        key = ("home", "|".join(selected) or "all")
        cached = self._cache.get(key)
        if cached and datetime.now(timezone.utc) - cached[0] < CACHE_TTL:
            return cached[1]
        result = self._collect(feeds, empty_message="Nenhuma notícia encontrada para as categorias selecionadas.")
        with self._lock:
            self._cache[key] = (datetime.now(timezone.utc), result)
        return result
