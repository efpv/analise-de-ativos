# Especificação Técnica — Pipeline de Dados de Mercado (B3 → Firestore)

**Versão:** 1.0  
**Data:** 2026-11-26  
**Status:** Proposto para implementação  
**Escopo:** Ingestão de cotações diárias e proventos dos últimos 5 anos para tickers configuráveis, persistência no Google Cloud Firestore e exposição para a aplicação FastAPI existente rodando no Cloud Run.

---

## 1. Contexto e objetivo

A aplicação `Preço Justo Bazin` já consome BRAPI/Yahoo Finance sob demanda em `app/services/api_client.py` e guarda apenas histórico de consultas e cache de cash-yield (SQLite ou Firestore, ver `app/repositories/firestore_store.py`). Isso torna cada análise dependente de fontes externas e não deixa um histórico estruturado de preços e eventos corporativos.

O pipeline proposto cria uma camada de dados persistente no Firestore:

- cotações diárias dos últimos 5 anos (`open`, `high`, `low`, `close`, `adj_close`, `volume`);
- proventos com `data_com`, `data_ex`, `data_pagamento`, `tipo_provento`, `valor_bruto` e `fonte`;
- funções de leitura prontas para o Cloud Run (`market_repository.py`);
- execução local, em Cloud Run Job ou via endpoint HTTP protegido.

Fontes obrigatórias e gratuitas:

- **Cotações:** `yfinance` com sufixo `.SA` e `auto_adjust=False`; leitura opcional de `COTAHIST_A<ANO>.TXT` da B3.
- **Proventos:** consulta pública de eventos corporativos da B3, com fallback limitado via dividendos do Yahoo Finance.

A especificação respeita as convenções atuais do repositório: Python 3.12+, `dataclasses`, type hints, Pydantic v2, `httpx`, `yfinance`, `google-cloud-firestore`, testes com pytest e configuração por variáveis de ambiente.

---

## 2. Decisões de arquitetura

| Decisão | Justificativa |
|---|---|
| Criar pacote top-level `src/` com os módulos pedidos na tarefa (`config`, `extractors`, `transformers`, `storage/firestore_client.py`, `repositories/market_repository.py`, `cli.py`). | Mantém o pipeline independente do ciclo de vida da API; pode rodar como Job sem importar `app`. |
| A aplicação FastAPI importa apenas `src.repositories.market_repository` e `src.config`. | Evita duplicar regras de leitura e mantém `app/` como camada de apresentação/API. |
| Reutilizar `google-cloud-firestore`, `httpx` e `yfinance` já presentes em `requirements.txt`. | Nenhuma dependência de runtime novo é obrigatória; apenas `google-auth` passa a ser explícita. |
| Manter `app/core/config.py` como fonte das configurações da API e `src/config.py` como fonte das configurações do pipeline. | Ambas leem o mesmo ambiente; `FIRESTORE_PROJECT`/`FIRESTORE_PREFIX` são compartilhados para consistência com `docs/configuracao-firestore.md`. |
| Ingestão principal via **Cloud Run Job**; API expõe somente leitura. | Um endpoint de escrita pública seria arriscado; o read model é suficiente para o consumo. |
| IDs determinísticos + `merge=True` em toda escrita. | Idempotência: reexecutar `--full` ou `--incremental` não duplica documentos. |
| Cotações anuais em subcollection, proventos em coleção raiz indexada. | Quantidade de documentos pequena e consultas por ticker/data eficientes. |

### 2.1 Relação com o código existente

- `app/services/ticker_service.py`: a validação de ticker continua na API. O pipeline terá `src/transformers/ticker.py` com a mesma regex; recomendado, em um segundo passo, fazer `TickerService.validate` delegar para essa função, evitando divergência.
- `app/repositories/firestore_store.py`: continua responsável por `asset_cache`, `cash_yield` e progresso. O novo pipeline usa coleções separadas (`ativos`, `proventos`) e não altera o comportamento atual.
- `app/api/routes.py`: recebe um novo endpoint de consulta; os endpoints de valuation/cash-yield não mudam.
- `docs/configuracao-firestore.md`: continua válido; basta adicionar o papel `roles/datastore.user` e, se usado, o prefixo.

### 2.2 Universo de tickers — não fica limitado a 4

Os quatro tickers do exemplo (`ITUB4`, `BBAS3`, `WEGE3`, `VALE3`) são apenas o **padrão de piloto** copiado da `tarefa.md`. O universo é configurável e pode expandir sem mudança de código:

| Modo | Como seleciona | Quantidade | Quando usar |
|---|---|---:|---|
| Piloto | `MARKET_TICKERS=ITUB4,BBAS3,WEGE3,VALE3` | 4 | Validar pipeline, custo e qualidade dos dados antes de escalar. |
| Catálogo local | `MARKET_TICKERS_FROM_CATALOG=true` ou `--catalog` | **376** | Produção: mesmas ações/unidades usadas pelo cash-yield em `data/ativos_b3.json` (`type in {"STOCK","UNIT"}` e ticker sem sufixo `F`). |
| Lista explícita | `MARKET_TICKERS_FILE=...` ou `--tickers-file ...` | variável | Universo curado próprio (JSON com `ticker` ou TXT linha por ticker). |
| Sobrescrita pontual | `--tickers BBB3,VALE3` | variável | Testes e execuções avulsas. |

O catálogo completo do arquivo tem 2.297 entradas (ETFs, BDRs, FIIs etc.), mas o recorte `STOCK`/`UNIT` é o mesmo de `CashYieldService.catalog_tickers()` e resulta em **376 ativos**. Incluir FIIs/ETFs exigiria revisar as regras de proventos (`RENDIMENTO`) e de `tipo_provento`; fica como evolução futura.

Impacto estimado ao escalar de 4 para 376 tickers:

| Item | 4 tickers | 376 tickers |
|---|---:|---:|
| Escritas na carga `--full` | ~130 | ~10.000 (ainda abaixo das 20.000/dia grátis) |
| Armazenamento | ~1 MB | ~100–120 MB (abaixo de 1 GiB grátis) |
| Duração do Job full | ~1 min | ~20–60 min (depende de yfinance/429) |
| Custo Firestore | R$ 0 | R$ 0 (dentro do free tier) |
| Custo Cloud Run Job | R$ 0 | R$ 0 (dentro do free tier; ajustar `--task-timeout`) |

O limite ao escalar é **tempo de execução e rate limit das fontes**, não custo. Por isso o retry/backoff e `MARKET_WORKERS` baixo continuam obrigatórios.

---

## 3. Árvore de pastas proposta

```text
PrecoJustoBazin/
├── .env.example                          # novo
├── Dockerfile                            # novo (imagem única para API e Job)
├── firestore.indexes.json                # novo (índice composto proventos)
├── requirements.txt                      # ajustado
├── src/                                  # novo pacote do pipeline
│   ├── __init__.py
│   ├── config.py                         # MarketSettings + load_settings()
│   ├── models.py                         # TypedDicts/dataclasses de domínio
│   ├── cli.py                            # argparse: --full / --incremental
│   ├── pipelines/
│   │   ├── __init__.py
│   │   └── market_pipeline.py            # orquestração por ticker
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── yfinance_quotes.py            # cotações via yfinance
│   │   ├── b3_cotahist.py                # cotações locais COTAHIST_A<ANO>.TXT
│   │   ├── b3_events.py                  # eventos corporativos B3 (httpx)
│   │   └── yahoo_dividends.py            # fallback limitado de proventos
│   ├── transformers/
│   │   ├── __init__.py
│   │   ├── ticker.py                     # normalize_ticker()
│   │   ├── catalog.py                    # catalog_tickers() — recorte STOCK/UNIT do JSON
│   │   ├── quotes.py                     # normalize_quotes()
│   │   └── proventos.py                  # datas, valores, tipo, evento_id
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── firestore_client.py           # ADC + Client(project, database)
│   │   └── batch_writer.py               # WriteBatch <= 500 ops
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── market_repository.py          # get_cotacoes() / get_proventos()
│   └── utils/
│       ├── __init__.py
│       ├── logging.py                    # logging estruturado (JSON)
│       └── retry.py                      # backoff exponencial com jitter
├── app/
│   ├── api/routes.py                     # + GET /api/v1/market/{ticker}
│   └── schemas/market.py                 # novo: modelos de resposta
├── docs/
│   ├── configuracao-firestore.md         # existente
│   ├── especificacao-tecnica-pipeline-mercado.md  # este documento
│   └── operacao-pipeline-mercado.md      # novo: runbook Cloud Run Job
└── app/tests/
    ├── test_market_transformers.py       # novo
    ├── test_market_extractors.py         # novo
    ├── test_market_storage.py            # novo
    ├── test_market_pipeline.py           # novo
    ├── test_market_repository.py         # novo
    └── test_market_api.py                # novo
```

---

## 4. Configuração

### 4.1 `requirements.txt`

Manter as dependências atuais e tornar explícita a autenticação:

```text
fastapi>=0.115
uvicorn>=0.32
httpx>=0.27
jinja2>=3.1
yfinance>=0.2.50
pytest>=8.3
pytest-cov>=5.0
google-cloud-firestore>=2.19
google-auth>=2.0          # novo (já vem transitivamente, mas explícito)
```

Não são necessários `tenacity`, `python-dotenv` nem bibliotecas de parse de COTAHIST: o retry é implementado em `src/utils/retry.py`, o `.env` é lido pelo runtime/`gcloud` e o layout da B3 é posicional.

### 4.2 `.env.example`

```dotenv
# --- Google Cloud / Firestore ---
GOOGLE_CLOUD_PROJECT=
FIRESTORE_PROJECT=              # legado da app; usado se GOOGLE_CLOUD_PROJECT vazio
FIRESTORE_DATABASE=(default)
FIRESTORE_PREFIX=               # legado da app; default para MARKET_FIRESTORE_PREFIX
MARKET_FIRESTORE_PREFIX=        # '' => coleções "ativos" e "proventos"

# --- Universo e janela ---
# Padrão de piloto (4). Para 376 STOCK/UNIT do catálogo, use o modo catálogo abaixo.
MARKET_TICKERS=ITUB4,BBAS3,WEGE3,VALE3
MARKET_TICKERS_FROM_CATALOG=false   # true => lê MARKET_CATALOG_PATH (ignora MARKET_TICKERS)
MARKET_CATALOG_PATH=data/ativos_b3.json
MARKET_TICKERS_FILE=                # alternativa: JSON/TXT com lista própria
MARKET_YEARS=5
MARKET_INCREMENTAL_DAYS=60
MARKET_MAX_RANGE_DAYS=3650

# --- Fontes ---
MARKET_B3_COTAHIST_DIR=         # ex.: ./data/cotahist; vazio => não usa arquivo local
MARKET_B3_EVENTS_URL=           # URL pública da consulta de eventos da B3; vazio => default do extrator

# --- Execução ---
MARKET_BATCH_SIZE=500           # limitado a 500
MARKET_MAX_RETRIES=3
MARKET_RETRY_BACKOFF=1.0
MARKET_WORKERS=2

# --- API (opcional) ---
MARKET_ADMIN_TOKEN=             # apenas se um endpoint de trigger for habilitado
```

### 4.3 `src/config.py`

```python
@dataclass(frozen=True)
class MarketSettings:
    tickers: tuple[str, ...]
    tickers_from_catalog: bool
    tickers_file: str
    catalog_path: str
    years: int
    incremental_days: int
    max_range_days: int
    google_cloud_project: str
    firestore_database: str
    collection_prefix: str
    cotahist_dir: str
    b3_events_url: str
    batch_size: int
    max_retries: int
    retry_base_delay: float
    workers: int
    admin_token: str

def load_settings() -> MarketSettings: ...
```

Regras de validação em `load_settings()`:

- Seleção do universo, nesta precedência:
  1. `MARKET_TICKERS_FROM_CATALOG=true` → `catalog_tickers(MARKET_CATALOG_PATH)`, que aplica o mesmo filtro de `CashYieldService.catalog_tickers()` (`type in {"STOCK","UNIT"}` e ticker sem sufixo `F`). Hoje resulta em **376** tickers.
  2. `MARKET_TICKERS_FILE` preenchido → lê `.json` (lista de objetos com `ticker`) ou `.txt` (um ticker por linha), com trim/uppercase/dedupe.
  3. `MARKET_TICKERS` → split por vírgula, trim, uppercase e dedupe mantendo ordem; padrão são os 4 do piloto.
  4. Nenhuma das opções → erro de configuração.
- `1 <= batch_size <= 500`; se maior, ajustar para 500 com aviso.
- `years > 0`, `incremental_days > 0`, `max_retries >= 0`, `workers >= 1`.
- `google_cloud_project` = `GOOGLE_CLOUD_PROJECT` → `FIRESTORE_PROJECT` → projeto ADC (`google.auth.default()`).
- `collection_prefix` = `MARKET_FIRESTORE_PREFIX` se definido, senão `FIRESTORE_PREFIX`; usado como `f"{prefix}ativos"` / `f"{prefix}proventos"`.
- Nenhuma chave ou token é logado.

> Nota: usar `field(default_factory=...)` nos campos derivados de `os.getenv`, seguindo boa prática de dataclasses, em vez de avaliar `os.getenv` na definição da classe.

---

## 5. Contratos de dados

### 5.1 `src/models.py`

```python
from typing import Literal, TypedDict

TipoProvento = Literal["DIVIDENDO", "JCP", "RENDIMENTO", "OUTRO"]

class Quote(TypedDict):
    data: str          # YYYY-MM-DD
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
```

### 5.2 Firestore — estrutura

#### `ativos/{ticker}`

| Campo | Tipo | Regra |
|---|---|---|
| `ticker` | string | Normalizado, uppercase. |
| `atualizado_em` | string | `datetime.now(timezone.utc).isoformat()`. |
| `inicio_serie` | string / null | Menor `data` de cotação existente. No incremental, `min(existente, novo)`. |
| `fim_serie` | string / null | Maior `data` de cotação existente. No incremental, `max(existente, novo)`. |
| `ultimo_provento_em` | string / null | Maior entre `data_pagamento`, `data_ex` e `data_com` dos eventos. |
| `quantidade_cotacoes` | int | Opcional, útil para auditoria. |
| `quantidade_proventos` | int | Opcional. |

#### `ativos/{ticker}/cotacoes_anuais/{ano}`

| Campo | Tipo | Regra |
|---|---|---|
| `ticker` | string | Uppercase. |
| `ano` | int | Ano do documento. |
| `atualizado_em` | string | UTC ISO. |
| `pregoes` | list[Quote] | Ordenado por `data`; unido por data no modo incremental. |

Dimensionamento: ~250 pregões/ano × ~180 bytes ≈ 45 KB por documento, bem abaixo do limite de 1 MB.

#### `proventos/{evento_id}`

`evento_id` determinístico:

```python
evento_id = f"{ticker}_{tipo_provento}_{data_com}_{valor_bruto:.6f}"
```

- Aplicar `round(valor_bruto, 6)` antes de formatar e armazenar, evitando diferenças de representação de float.
- Sanitizar caracteres fora de `[A-Za-z0-9_.-]` com `_` (defensivo; tickers e tipos já são seguros).
- Campos indexáveis: `ticker`, `data_com`, `data_ex`, `data_pagamento`, `tipo_provento`, `valor_bruto`, `fonte`.
- `data_com`/`data_ex`/`data_pagamento` são strings ISO `YYYY-MM-DD` para permitir comparação lexicográfica nas consultas.

#### `firestore.indexes.json`

Necessário para `where(ticker == ...) + where(data_com >= ...) + order_by(data_com)`:

```json
{
  "indexes": [
    {
      "collectionGroup": "proventos",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "ticker", "order": "ASCENDING" },
        { "fieldPath": "data_com", "order": "ASCENDING" }
      ]
    }
  ],
  "fieldOverrides": []
}
```

Se `MARKET_FIRESTORE_PREFIX` estiver ativo, o `collectionGroup` deve refletir o nome prefixado.

---

## 6. Componentes

### 6.1 `src/utils/retry.py`

```python
def retry(
    func: Callable[[], T],
    *,
    attempts: int,
    base_delay: float,
    retryable: tuple[type[Exception], ...],
) -> T: ...
```

- Backoff exponencial: `base_delay * 2 ** (tentativa - 1)` com jitter de ±20%.
- Repetir em chamadas externas: `httpx.HTTPStatusError` com status 429/5xx, `httpx.TimeoutException`, `yfinance` exceptions, `OSError`.
- Repetir em Firestore: `ServiceUnavailable`, `DeadlineExceeded`, `InternalServerError`, `TooManyRequests`, `Aborted`.
- **Não** repetir: `PermissionDenied`, `NotFound`, `InvalidArgument`, 4xx (exceto 429).
- Logar `tentativa`, `tipo_erro` e `ticker`; nunca corpo da resposta nem token.

### 6.2 `src/utils/logging.py`

`configure_logging(level: str)` instala um `Formatter` que emite JSON por linha:

```json
{
  "timestamp": "2026-11-26T12:00:00+00:00",
  "level": "INFO",
  "logger": "src.pipelines.market_pipeline",
  "message": "ticker_concluido",
  "ticker": "ITUB4",
  "modo": "full",
  "cotacoes": 1243,
  "proventos": 18,
  "duracao_ms": 3210
}
```

Campos extras são passados via `extra={...}`, padrão já usado em `app/services/api_client.py`.

### 6.3 `src/storage/firestore_client.py`

```python
def get_client(settings: MarketSettings | None = None) -> firestore.Client:
    credentials, default_project = google.auth.default()
    project = settings.google_cloud_project or default_project
    return firestore.Client(
        project=project,
        database=settings.firestore_database,
        credentials=credentials,
    )
```

- Sem credenciais hardcoded; usa ADC.
- Local: `gcloud auth application-default login` ou `GOOGLE_APPLICATION_CREDENTIALS`.
- Cloud Run: conta de serviço com `roles/datastore.user`.
- `FIRESTORE_DATABASE` default `(default)`; suporta bancos nomeados.

### 6.4 `src/storage/batch_writer.py`

```python
class BatchedWriter:
    def __init__(self, client: firestore.Client, batch_size: int = 500) -> None: ...
    def set(self, reference, data: dict, *, merge: bool = True) -> None: ...
    def flush(self) -> None: ...
    def __enter__(self) -> "BatchedWriter": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
```

- Acumula até `batch_size` (máx. 500) operações e chama `batch.commit()` com retry.
- Após commit, cria novo batch.
- `__exit__` faz flush se houver operações pendentes; em caso de exceção, não esconde o erro original.
- Todo `set` usa `merge=True`.

### 6.5 Extractors

| Módulo | Função | Detalhes |
|---|---|---|
| `yfinance_quotes.py` | `extract(ticker, start, end) -> list[Quote]` | `yf.Ticker(f"{ticker}.SA").history(start=start, end=end, auto_adjust=False, actions=False, progress=False, threads=False)`. Renomeia `Open/High/Low/Close/Adj Close/Volume`. `end` é exclusivo; o pipeline passa `end + 1 dia`. DataFrame vazio retorna `[]`. |
| `b3_cotahist.py` | `extract(ticker, year, directory) -> list[Quote]` | Lê `COTAHIST_A{year}.TXT`, filtra registro `01` e código de negociação igual ao ticker (trim). Layout posicional conforme manual oficial da B3 (245 bytes/registro). `adj_close = close` quando não há fator de ajuste disponível; esse fato é registrado em aviso. |
| `b3_events.py` | `extract(ticker, start, end) -> list[EventoProvento]` | `httpx.AsyncClient`/`httpx.Client` com timeout configurável e retry. URL default configurável por `MARKET_B3_EVENTS_URL`. Parser isolado em classe `B3EventsPayloadParser` para absorver mudanças de schema. Mapeia tipo B3 → `DIVIDENDO`/`JCP`/`RENDIMENTO`/`OUTRO`. |
| `yahoo_dividends.py` | `extract(ticker, start, end) -> list[EventoProvento]` | Fallback quando a B3 falha ou não retorna eventos. Usa `stock.dividends`; `data_ex` = índice do evento; `data_com` = mesma `data_ex` (limitação explícita); `data_pagamento = None`; `tipo_provento = "OUTRO"`; `fonte = "Yahoo Finance (data ex como data_com)"`. |

Precedência de cotações: `yfinance` como base; `COTAHIST` preenche/substitui datas presentes no arquivo local (fonte oficial B3). Dedupe por `data`, mantendo a última ocorrência.

### 6.6 Transformers

- `ticker.normalize_ticker(value) -> str`: trim + uppercase; valida com a mesma regex de `TickerService.validate` (`[A-Z0-9]{4}[0-9]{1,2}[A-Z]?F?`).
- `catalog.catalog_tickers(path) -> tuple[str, ...]`: lê `data/ativos_b3.json`, filtra `type in {"STOCK","UNIT"}` e exclui tickers terminados em `F`; retorna 376 tickers ordenados. Teste de paridade com `CashYieldService.catalog_tickers()` garante que o pipeline e o cash-yield usem o mesmo universo.
- `proventos.parse_date(value) -> str | None`: aceita `YYYY-MM-DD`, `DD/MM/YYYY`, `YYYYMMDD`; saída ISO.
- `proventos.parse_brl_number(value) -> float | None`: remove `R$`, espaços e separador de milhar; troca vírgula por ponto; rejeita `NaN`/`inf`.
- `proventos.classify(raw_tipo) -> TipoProvento`: normaliza acentos/caixa; `"DIVIDENDO"` para dividendo, `"JCP"` para juros sobre capital próprio, `"RENDIMENTO"` para rendimentos (FIIs), `"OUTRO"` para o restante.
- `proventos.make_event_id(...)`: conforme §5.2.
- `quotes.normalize_quotes(rows) -> list[Quote]`: converte timestamps tz-aware para `date`, ordena por `data`, dedupe.
- `proventos.normalize_events(rows, ticker) -> list[EventoProvento]`: dedupe por `evento_id`, ordena por `data_com`.

### 6.7 `src/pipelines/market_pipeline.py`

```python
@dataclass(frozen=True)
class TickerResult:
    ticker: str
    cotacoes: int
    proventos: int
    erros: tuple[str, ...]
    duracao_ms: int

def run(
    *,
    modo: Literal["full", "incremental"],
    tickers: tuple[str, ...] | None = None,
    settings: MarketSettings | None = None,
    client: firestore.Client | None = None,
) -> tuple[TickerResult, ...]: ...
```

Passos por ticker:

1. **Janela**
   - `full`: `inicio = date(today.year - years, today.month, today.day)` com guarda para 29/02 → 28/02; `fim = today`.
   - `incremental`: `inicio = today - timedelta(days=incremental_days)`; `fim = today`.
   - `end_exclusivo = fim + timedelta(days=1)` para `yfinance`.

2. **Extração**
   - Cotações via `yfinance_quotes.extract`, complementadas por `b3_cotahist` se `MARKET_B3_COTAHIST_DIR` estiver definido.
   - Proventos via `b3_events.extract`; se falhar/retornar vazio, tentar `yahoo_dividends.extract` e registrar aviso.

3. **Transformação**
   - `normalize_quotes`, `normalize_events`.
   - Agrupar cotações por `ano`.

4. **Merge incremental**
   - Para cada ano tocado, ler `ativos/{ticker}/cotacoes_anuais/{ano}` existente.
   - Construir mapa `{data: Quote}` com existentes + novos (novos sobrescrevem a mesma data).
   - Reescrever `pregoes` ordenado. Isso evita que o modo incremental apague dias antigos com `merge=True`.

5. **Metadados**
   - Ler `ativos/{ticker}` existente.
   - `inicio_serie = min(existente, novo)`, `fim_serie = max(existente, novo)`.
   - `ultimo_provento_em = max(existente, max(datas dos eventos))`.
   - Atualizar `atualizado_em` e contadores.

6. **Escrita**
   - `BatchedWriter` com `merge=True` para: 1 doc de ativo + N docs anuais + N docs de proventos.
   - Commit por chunk de no máximo 500 operações.

7. **Isolamento de falhas**
   - `try/except` por ticker; falha de um não aborta o lote.
   - Erros inesperados são logados com `logger.exception` incluindo `ticker`, mas sem payload.

### 6.8 `src/cli.py`

```bash
python -m src.cli --full                                  # piloto: 4 tickers do .env
python -m src.cli --incremental                           # piloto
python -m src.cli --full --catalog                        # produção: 376 STOCK/UNIT
python -m src.cli --incremental --catalog --workers 2     # diário, universo completo
python -m src.cli --full --tickers ITUB4,BBAS3 --dry-run
python -m src.cli --full --tickers-file ./meus_tickers.txt
```

| Argumento | Default | Descrição |
|---|---|---|
| `--full` / `--incremental` | `--full` | Modo de execução (mutuamente exclusivos). |
| `--tickers` | `MARKET_TICKERS` | Sobrescreve lista do ambiente. |
| `--catalog` | `MARKET_TICKERS_FROM_CATALOG` | Usa os 376 `STOCK`/`UNIT` de `data/ativos_b3.json`; tem precedência sobre `--tickers`. |
| `--catalog-path` | `MARKET_CATALOG_PATH` | Caminho alternativo do catálogo. |
| `--tickers-file` | `MARKET_TICKERS_FILE` | JSON/TXT com lista própria de tickers. |
| `--years` | `MARKET_YEARS` | Apenas no modo full. |
| `--days` | `MARKET_INCREMENTAL_DAYS` | Apenas no incremental. |
| `--cotahist-dir` | `MARKET_B3_COTAHIST_DIR` | Diretório dos arquivos anuais da B3. |
| `--project`, `--database` | env | Sobrescrevem projeto/banco Firestore. |
| `--workers` | `MARKET_WORKERS` | Paralelismo entre tickers. |
| `--dry-run` | `False` | Executa extração/transformação e loga contagens sem escrever. |
| `--log-level` | `INFO` | Nível de log estruturado. |

Códigos de saída: `0` sucesso; `1` falha parcial (algum ticker falhou); `2` erro de configuração.

### 6.9 `src/repositories/market_repository.py` — API de leitura

```python
def get_cotacoes(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    client: firestore.Client | None = None,
    settings: MarketSettings | None = None,
) -> list[Quote]: ...

def get_proventos(
    ticker: str,
    start_date: str | None = None,
    *,
    client: firestore.Client | None = None,
    settings: MarketSettings | None = None,
) -> list[EventoProvento]: ...
```

Assinaturas pedidas na tarefa mantidas; parâmetros extras são keyword-only e opcionais, permitindo injeção de client em testes.

**`get_cotacoes`**

1. Normaliza ticker e valida `YYYY-MM-DD` com `date.fromisoformat`; `start <= end`, senão `ValueError`.
2. Determina anos `range(start.year, end.year + 1)`.
3. Para cada ano, tenta ler `ativos/{ticker}/cotacoes_anuais/{ano}`; documento inexistente é ignorado.
4. Filtra `pregoes` por `start_date <= data <= end_date`.
5. Ordena por `data` e retorna.

**`get_proventos`**

1. Normaliza ticker; valida `start_date` se informado.
2. Query em `proventos`:
   - `where(FieldFilter("ticker", "==", ticker))`
   - se `start_date`: `where(FieldFilter("data_com", ">=", start_date))`
   - `order_by("data_com")`
3. Retorna lista de `EventoProvento` com `evento_id` incluído.

Para evitar erro de índice em ambientes ainda sem `firestore.indexes.json`, a implementação pode fazer fallback: consultar apenas por `ticker`, filtrar `data_com` em Python e ordenar localmente. O comportamento padrão, porém, deve usar o índice composto.

---

## 7. Integração com a aplicação FastAPI

### 7.1 Novo schema — `app/schemas/market.py`

```python
from datetime import date
from typing import Literal
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
```

### 7.2 Novo endpoint — `app/api/routes.py`

```python
@router.get("/api/v1/market/{ticker}", response_model=MarketDataResponse)
def get_market_data(
    ticker: str,
    inicio: date | None = Query(default=None),
    fim: date | None = Query(default=None),
    incluir_cotacoes: bool = Query(default=True),
    incluir_proventos: bool = Query(default=True),
): ...
```

Regras:

- Ticker validado por `ticker_service.validate(ticker)` (400 se inválido).
- Se `inicio`/`fim` omitidos: `fim = hoje`, `inicio = hoje - years` usando `src.config.load_settings()`.
- Intervalo máximo `MARKET_MAX_RANGE_DAYS` (default 3650); acima disso, 400.
- `inicio > fim` → 400.
- Coleta `avisos` quando uma fonte retorna vazia ou quando o fallback Yahoo é usado.
- Exceção do Firestore/ADC → `503` com mensagem genérica; sem detalhes de credencial ou URL.
- Resposta 200 com listas vazias e aviso quando não houver dados para o período.

Exemplo:

```bash
curl "http://127.0.0.1:8000/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31"
```

```json
{
  "ticker": "ITUB4",
  "inicio": "2024-01-01",
  "fim": "2024-12-31",
  "cotacoes": [
    {"data": "2024-01-02", "open": 35.1, "high": 35.5, "low": 34.9,
     "close": 35.2, "adj_close": 35.2, "volume": 12345678}
  ],
  "proventos": [
    {"evento_id": "ITUB4_DIVIDENDO_2024-05-20_0.450000", "ticker": "ITUB4",
     "tipo_provento": "DIVIDENDO", "data_com": "2024-05-20",
     "data_ex": "2024-05-17", "data_pagamento": "2024-05-24",
     "valor_bruto": 0.45, "fonte": "B3"}
  ],
  "avisos": []
}
```

> Um endpoint de trigger (`POST /api/v1/market/ingest`) **não** faz parte do escopo inicial. Se for necessário no futuro, deve ser protegido por `MARKET_ADMIN_TOKEN` ou IAM e executar em background, seguindo o padrão de `/api/v1/cash-yield/refresh`.

### 7.3 Dockerfile

Imagem única; o Cloud Run Service usa o `CMD`, o Cloud Run Job sobrescreve os args.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY src ./src
COPY data ./data

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## 8. Execução no Cloud Run

### 8.1 Cloud Run Job (carga inicial)

```bash
gcloud run jobs create bazin-market-full \
  --image <REGIAO>-docker.pkg.dev/<PROJETO>/<REPO>/preco-justo-bazin:latest \
  --region <REGIAO> \
  --project <PROJETO> \
  --service-account <CONTA_DE_SERVICO> \
  --set-env-vars "MARKET_TICKERS=ITUB4,BBAS3,WEGE3,VALE3,MARKET_YEARS=5" \
  --args="--full" \
  --max-retries=2 \
  --task-timeout=30m

gcloud run jobs execute bazin-market-full --region <REGIAO> --project <PROJETO>
```

Para o universo completo, troque o `--set-env-vars` por `MARKET_TICKERS_FROM_CATALOG=true` e aumente o `--task-timeout` para `60m`: o full de 376 tickers pode levar de 20 a 60 min por causa do rate limit do yfinance.

### 8.2 Cloud Run Job (incremental)

```bash
gcloud run jobs create bazin-market-incremental \
  --image <...> \
  --region <REGIAO> \
  --service-account <CONTA_DE_SERVICO> \
  --set-env-vars "MARKET_TICKERS=ITUB4,BBAS3,WEGE3,VALE3" \
  --args="--incremental" \
  --task-timeout=10m
```

Para o universo completo, use `MARKET_TICKERS_FROM_CATALOG=true` e `--task-timeout=30m` (o incremental de 376 tickers também sofre rate limit).

Agendar com Cloud Scheduler usando autenticação OIDC contra a conta de serviço com permissão de invocar Jobs.

### 8.3 Permissões

A conta de serviço precisa de `roles/datastore.user` (conforme `docs/configuracao-firestore.md`). Não conceder `roles/owner` nem papéis de edição de IAM.

### 8.4 Ordem de deploy

1. Aplicar `firestore.indexes.json` (`gcloud firestore indexes composite create --file ...` ou via Console).
2. Publicar imagem com `src/` incluído.
3. Criar/atualizar os Jobs.
4. Rodar `--full` uma vez.
5. Validar endpoint `GET /api/v1/market/{ticker}`.
6. Agendar `--incremental` (diário recomendado).

---

## 9. Resiliência, segurança e limites

| Tema | Regra |
|---|---|
| Retries | Backoff exponencial com jitter, no máximo `MARKET_MAX_RETRIES`. |
| Falha por ticker | Registrada e continuing; lote termina com exit code 1 se houver alguma falha. |
| Firestore batch | Máximo 500 operações; `merge=True` sempre. |
| Tamanho de documento | `pregoes` anual ~45 KB; monitorar se mais de 1 MB (não esperado com 5 anos). |
| Credenciais | Somente ADC; nenhuma chave em código, log ou resposta de API. |
| Logs | JSON estruturado; nunca incluir `BRAPI_API_KEY`, `MARKET_ADMIN_TOKEN`, URL completa ou corpo de resposta. |
| Rate limiting | `MARKET_WORKERS` baixo (2) e retry em 429; não disparar milhares de requisições simultâneas. |
| Dados parciais | Yahoo como fallback têm `data_com = data_ex` e `data_pagamento = None`; sinalizado em `avisos`. |
| COTAHIST local | `adj_close = close` se não houver fator de ajuste; sinalizado em `avisos`. |
| Exclusão | Fora de escopo: eventos removidos na fonte não são apagados automaticamente. Implementar `--prune` em versão futura se necessário. |

---

## 10. Testes

### 10.1 Cobertura planejada

| Arquivo de teste | Casos principais |
|---|---|
| `test_market_transformers.py` | `normalize_ticker`, `catalog_tickers()` com os 376 ativos e paridade com `CashYieldService.catalog_tickers()`, parse de datas em 3 formatos, parse de `R$ 1.234,56`, classificação JCP/DIVIDENDO/RENDIMENTO/OUTRO, `evento_id` determinístico, dedupe/ordenação. |
| `test_market_extractors.py` | `yfinance.history` mockado com `auto_adjust=False`; fixture de linha COTAHIST; payload B3 mockado via `httpx.MockTransport`; fallback Yahoo com ex-date. |
| `test_market_storage.py` | `BatchedWriter` respeita 500; `merge=True`; `get_client` usa `project`/`database` e ADC mockado; retry em `ServiceUnavailable`, sem retry em `PermissionDenied`. |
| `test_market_pipeline.py` | Janela full = 5 anos com guarda 29/02; incremental = 60 dias; merge de `pregoes` preserva datas antigas; metadados `min`/`max`; falha de um ticker não aborta; `--dry-run` não escreve. |
| `test_market_repository.py` | Filtro de intervalo inclusivo, anos inexistentes ignorados, ordenação, query `proventos` com e sem `start_date`, client injetado. |
| `test_market_api.py` | 200 com cotacoes+proventos; 400 para ticker/intervalo inválidos; 503 em erro do repositório; avisos presentes. |

### 10.2 Comandos

```bash
python -m pytest --cov=app --cov=src --cov-report=term-missing
node --test app/tests/test_ranking_ui.js app/tests/test_asset_search.js
```

Os testes existentes não devem ser alterados; o novo endpoint é aditivo.

---

## 11. Critérios de aceite

1. `MARKET_TICKERS=ITUB4 python -m src.cli --full` cria `ativos/ITUB4`, `ativos/ITUB4/cotacoes_anuais/{2021..2026}` e documentos em `proventos` com todos os campos tipados.
2. `python -m src.cli --full --catalog --dry-run` processa exatamente os 376 tickers do recorte `STOCK`/`UNIT`, com falha isolada por ativo e sem escrita.
3. Rodar o mesmo comando duas vezes mantém a quantidade de documentos em `proventos` inalterada (idempotência).
4. `get_cotacoes("ITUB4", "2024-01-01", "2024-12-31")` retorna lista ordenada, com `data`, `open`, `high`, `low`, `close`, `adj_close`, `volume` e sem datas fora do intervalo.
5. `get_proventos("ITUB4", "2023-01-01")` retorna somente eventos com `data_com >= 2023-01-01`.
6. `--incremental` atualiza os últimos 60 dias **sem remover** pregões anteriores do mesmo ano.
7. `GET /api/v1/market/ITUB4` devolve JSON consolidado com `cotacoes`, `proventos` e `avisos`.
8. Falha simulada da B3 aciona fallback Yahoo com aviso explícito sobre `data_com`/`data_pagamento`.
9. Nenhum log contém token, chave, URL de requisição ou corpo de resposta.
10. Suíte pytest completa passa, incluindo os testes antigos.

---

## 12. Fora de escopo / evoluções futuras

- Crossing completo BRAPI ↔ B3 ↔ Yahoo para recuperar `data_pagamento` ausente no fallback.
- Classificação automática de JCP vs dividendos quando a fonte não informar o tipo.
- `--prune` para remover eventos que desapareceram da fonte.
- Interface web para consultar o histórico persistido (o endpoint JSON já habilita isso).
- Substituição do cache de cash-yield pelo histórico persistido, com backtest de y1 usando preço da época (hoje indisponível).
- Migração de `TickerService.validate` para `src.transformers.ticker.normalize_ticker` como única fonte da regex.
