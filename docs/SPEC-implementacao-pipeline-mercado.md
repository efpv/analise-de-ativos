# SPEC de Implementação — Pipeline de Dados de Mercado (B3 → Firestore)

**Versão:** 1.0
**Data:** 2026-11-26
**Status:** Pronto para implementação; a fonte oficial de eventos da B3 depende de confirmação de URL/schema (§11).
**Documentos de origem:**
- PRD: [`docs/PRD-pipeline-mercado.md`](PRD-pipeline-mercado.md) (v1.0)
- Especificação técnica: [`docs/especificacao-tecnica-pipeline-mercado.md`](especificacao-tecnica-pipeline-mercado.md) (v1.0)
- Pedido original: [`tarefa.md`](../tarefa.md)

> Esta SPEC detalha **como implementar** o que o PRD define como produto. Ela não substitui a especificação técnica: onde houver divergência de arquitetura, vale a especificação técnica; onde houver detalhe de execução, contrato de função, mensagem de erro ou caso de teste, vale esta SPEC. Todos os identificadores `RF-xx` referenciam os requisitos funcionais do PRD.

**Como usar:** implemente na ordem de §8 (F0 → F5). Cada fase lista arquivos, contratos e gates de teste. Os contratos de configuração, dados, componentes, API e testes estão em §3–§7; operação e riscos em §10–§11. O checklist final está em §12.

---

## 1. Escopo e resultado esperado

### 1.1 Entrega

Pacote Python `src/` independente da aplicação, com pipeline de ingestão de cotações e proventos no Firestore, CLI operável em Cloud Run Job e repositório de leitura consumido por um endpoint aditivo `GET /api/v1/market/{ticker}`.

### 1.2 Fora do escopo (v1)

Conforme PRD §5.2: `POST /api/v1/market/ingest`, `--prune`, FIIs/ETFs/BDRs, tela web de histórico, substituição do cache de cash-yield, classificação automática de JCP e unificação da regex de ticker.

### 1.3 Invariantes que não podem ser violadas

1. Nenhum endpoint, schema, teste ou regra de negócio existente muda de contrato (RF-19/RNF-11).
2. `app/` não importa `src.extractors`, `src.pipelines`, `src.storage` nem `src.cli`; importa apenas `src.config` e `src.repositories.market_repository`.
3. `src/` não importa nada de `app/` (evita ciclo e permite rodar o Job sem carregar FastAPI).
4. Toda escrita no Firestore é idempotente (`merge=True` + ID determinístico).
5. Nenhum log, resposta HTTP ou mensagem de erro contém chave, token, URL completa ou corpo de resposta.
6. `--dry-run` não cria cliente Firestore e não exige ADC.

---

## 2. Decisões de implementação

| # | Decisão | Justificativa |
|---|---|---|
| D1 | Separar **carregamento de configuração** de **resolução de projeto via ADC**. `load_settings(resolve_adc_project=False)` nunca chama `google.auth.default()`. | O endpoint de leitura só precisa de `years` e `max_range_days`; resolver ADC no request quebraria testes e adicionaria latência/erro de credencial no caminho de leitura. |
| D2 | `src/models.py` usa `TypedDict` (não dataclass) para `Quote` e `EventoProvento`. | São dicionários persistidos no Firestore; `TypedDict` documenta o contrato sem custo de conversão. `TickerResult` e `MarketSettings` continuam `dataclass(frozen=True)`. |
| D3 | `evento_id` é gerado por `make_event_id()` e **sanitizado** para `[A-Za-z0-9_.-]`, trocando o restante por `_`. | IDs de documento Firestore não podem conter `/`; defensivo contra tipos/fontes inesperados. |
| D4 | `quantidade_cotacoes` é o total de pregões armazenados após a execução; `quantidade_proventos` é o total de eventos do ticker **no lote atual** (não é contagem global). | Evita leitura de todos os documentos de proventos a cada execução; os campos são opcionais e servem para auditoria do lote. |
| D5 | Merge incremental é feito em Python: lê o documento anual existente, une por `data` e reescreve `pregoes` completo. | `merge=True` em lista substitui a lista inteira; sem a união, o incremental apagaria dias antigos. |
| D6 | `get_proventos()` usa o índice composto; se o Firestore responder `FailedPrecondition` (índice ausente), refaz a consulta só por `ticker`, filtra e ordena em Python, com `logger.warning`. | Permite operar antes da criação do índice sem mascarar erros de permissão. |
| D7 | O extrator B3 exige `MARKET_B3_EVENTS_URL` para tentar a fonte oficial. Se vazia, registra aviso e vai direto ao fallback Yahoo. | Evita fixar em código uma URL pública que pode mudar; o pipeline continua funcional. A definição da URL oficial é pré-requisito de F1 (§11). |
| D8 | Datas de "hoje" usam o fuso fixo `UTC-03:00` (`B3_TZ`), sem `tzdata`. | Brasil não observa horário de verão desde 2019; evita dependência extra no Windows e mantém a data do pregão alinhada à B3. |
| D9 | Avisos de fallback são derivados dos dados persistidos na leitura (`fonte` do evento), não de metadados do pipeline. | O endpoint não precisa de estado extra e o aviso continua correto após reinícios. |
| D10 | `src/config.py` não mantém `settings` global; cada chamada recebe `env` opcional e retorna um `MarketSettings` imutável. | Testabilidade sem `monkeypatch` de módulo e sem vazamento de estado entre testes. |

---

## 3. Configuração

`app/core/config.py` permanece inalterado. A API lê apenas `years` e `max_range_days` via `src.config.load_settings(resolve_adc_project=False)`.

### 3.1 Variáveis de ambiente

| Variável | Tipo | Default | Validação / uso |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | str | vazio | 1ª opção de projeto Firestore. |
| `FIRESTORE_PROJECT` | str | vazio | 2ª opção; fallback para projeto ADC. |
| `FIRESTORE_DATABASE` | str | `(default)` | Repassado a `firestore.Client(database=...)`. |
| `MARKET_FIRESTORE_PREFIX` | str | vazio | Prefixo das coleções; se vazio, usa `FIRESTORE_PREFIX`. |
| `FIRESTORE_PREFIX` | str | vazio | Fallback legado do prefixo. |
| `MARKET_TICKERS` | csv | `ITUB4,BBAS3,WEGE3,VALE3` | Split por vírgula, trim, uppercase, dedupe mantendo ordem. |
| `MARKET_TICKERS_FROM_CATALOG` | bool | `false` | `true`/`1`/`yes` (case-insensitive) ativa catálogo. |
| `MARKET_CATALOG_PATH` | path | `data/ativos_b3.json` | Relativo à raiz do repositório. |
| `MARKET_TICKERS_FILE` | path | vazio | `.json` (lista de objetos com `ticker`) ou `.txt` (1 por linha). |
| `MARKET_YEARS` | int | `5` | `> 0`. |
| `MARKET_INCREMENTAL_DAYS` | int | `60` | `> 0`. |
| `MARKET_MAX_RANGE_DAYS` | int | `3650` | `> 0`; usado pela API. |
| `MARKET_B3_COTAHIST_DIR` | path | vazio | Se vazio, não lê COTAHIST. |
| `MARKET_B3_EVENTS_URL` | url | vazio | Se vazio, B3 é pulada com aviso (D7). |
| `MARKET_BATCH_SIZE` | int | `500` | `1..500`; acima de 500 vira 500 com aviso. |
| `MARKET_MAX_RETRIES` | int | `3` | `>= 0` (0 = sem retry). |
| `MARKET_RETRY_BACKOFF` | float | `1.0` | `> 0`; base do backoff em segundos. |
| `MARKET_WORKERS` | int | `2` | `>= 1`. |
| `MARKET_ADMIN_TOKEN` | str | vazio | Reservado para v2; **não** é usado na v1. |

### 3.2 Contrato de `src/config.py`

```python
class ConfigurationError(ValueError):
    """Configuração inválida; o CLI converte em exit code 2."""

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

def load_settings(
    *,
    env: Mapping[str, str] | None = None,
    resolve_adc_project: bool = True,
) -> MarketSettings: ...

def collection_name(settings: MarketSettings, name: str) -> str: ...
def read_tickers_file(path: str | Path) -> tuple[str, ...]: ...
```

Regras de `load_settings`:

1. Ler `env or os.environ` uma única vez; nunca ler `os.getenv` no corpo da dataclass.
2. Universo, nesta ordem, **após aplicar os overrides do CLI (§3.4)**:
   1. `MARKET_TICKERS_FROM_CATALOG=true` → `catalog_tickers(catalog_path)`.
   2. `MARKET_TICKERS_FILE` preenchido → `read_tickers_file(path)`.
   3. `MARKET_TICKERS` → lista normalizada.
   4. Nenhum resultado → `ConfigurationError("Nenhum universo de tickers configurado.")`.
3. Validações numéricas com mensagem específica:
   - `years > 0` → `"MARKET_YEARS deve ser maior que zero."`
   - `incremental_days > 0` → `"MARKET_INCREMENTAL_DAYS deve ser maior que zero."`
   - `max_retries >= 0` → `"MARKET_MAX_RETRIES não pode ser negativo."`
   - `workers >= 1` → `"MARKET_WORKERS deve ser pelo menos 1."`
   - `batch_size >= 1`; se `> 500`, ajustar para 500 e `logger.warning("batch_size_ajustado", extra={"batch_size": 500})`.
   - `retry_base_delay > 0` → `"MARKET_RETRY_BACKOFF deve ser maior que zero."`
4. `collection_prefix = MARKET_FIRESTORE_PREFIX or FIRESTORE_PREFIX or ""`.
5. Projeto: se `GOOGLE_CLOUD_PROJECT`/`FIRESTORE_PROJECT` preenchido, usa. Senão:
   - `resolve_adc_project=False` → string vazia (sem ADC).
   - `resolve_adc_project=True` → `google.auth.default()[1]`; se falhar, `ConfigurationError("Projeto Google Cloud não configurado e ADC indisponível.")`.
6. `collection_name(settings, "ativos")` → `f"{prefix}ativos"`; idem `proventos`.
7. Nunca logar `admin_token`, `b3_events_url` completa ou qualquer chave.

A resolução efetiva do projeto para o `firestore.Client` ocorre em `get_client` (§5.12): usa `google_cloud_project` quando preenchido e, caso contrário, o projeto devolvido por `google.auth.default()`.

### 3.3 Leitura de arquivo de tickers

`read_tickers_file(path)`:

- `.json`: aceita lista de strings ou lista de objetos com chave `ticker`.
- `.txt`: uma entrada por linha; ignora linhas vazias e iniciadas por `#`.
- Aplica `normalize_ticker` em cada item; remove duplicados mantendo a primeira ocorrência.
- Arquivo inexistente, JSON inválido ou lista vazia → `ConfigurationError`.

### 3.4 Precedência CLI × ambiente

| Prioridade | Origem | Observação |
|---:|---|---|
| 1 | `--catalog` ou `MARKET_TICKERS_FROM_CATALOG=true` | Vence inclusive `--tickers` (RF-01). |
| 2 | `--tickers-file` | Vence `--tickers`. |
| 3 | `--tickers` | Sobrescreve `MARKET_TICKERS` e `MARKET_TICKERS_FILE` do ambiente. |
| 4 | `MARKET_TICKERS_FILE` | — |
| 5 | `MARKET_TICKERS` | Default do piloto. |
| 6 | — | `ConfigurationError` → exit 2. |

Para a precedência funcionar, o CLI ajusta o `env` antes de chamar `load_settings`:

- `--catalog` define `MARKET_TICKERS_FROM_CATALOG=true` e remove `MARKET_TICKERS_FILE`/`MARKET_TICKERS`.
- `--tickers-file` define `MARKET_TICKERS_FILE` e remove `MARKET_TICKERS`.
- `--tickers` define `MARKET_TICKERS` e remove `MARKET_TICKERS_FILE`.
- `--catalog-path`, `--years`, `--days`, `--cotahist-dir`, `--project`, `--database` e `--workers` sobrescrevem a variável correspondente.

---

## 4. Modelo de dados

### 4.1 `src/models.py`

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

Regras de serialização:

- `data`, `data_com`, `data_ex`, `data_pagamento` sempre `YYYY-MM-DD` ou `None` (exceto `data_com`, obrigatório).
- `valor_bruto` e preços: `float` finito; `NaN`/`inf` são rejeitados na transformação, nunca chegam ao Firestore.
- `volume`: `int`; valor ausente ou `NaN` vira `0`.
- Não persistir campos extras do yfinance (ex.: `Stock Splits`, `Dividends`).

### 4.2 Coleções Firestore

#### `ativos/{ticker}`

| Campo | Tipo | Semântica |
|---|---|---|
| `ticker` | string | Uppercase. |
| `atualizado_em` | string | `datetime.now(timezone.utc).isoformat()`. |
| `inicio_serie` | string \| null | Menor `data` entre o existente e o novo; `null` se não houver cotação. |
| `fim_serie` | string \| null | Maior `data` entre o existente e o novo; `null` se não houver cotação. |
| `ultimo_provento_em` | string \| null | Máximo entre `data_pagamento`, `data_ex` e `data_com` de todos os eventos conhecidos. |
| `quantidade_cotacoes` | int | Total de pregões armazenados após o merge dos anos tocados (D4). |
| `quantidade_proventos` | int | Total de eventos processados no lote atual (D4). |

#### `ativos/{ticker}/cotacoes_anuais/{ano}`

| Campo | Tipo | Semântica |
|---|---|---|
| `ticker` | string | Uppercase. |
| `ano` | int | Ano do documento. |
| `atualizado_em` | string | UTC ISO. |
| `pregoes` | list[Quote] | Ordenado por `data`; sem datas duplicadas. |

Regras:

- O ID do documento é o ano com 4 dígitos (`2025`), sem zero à esquerda.
- Um documento só é escrito se houver pelo menos um pregão para o ano após o merge.
- Nunca remover anos fora da janela atual.
- Se a extração não trouxer cotações, **não** sobrescrever `pregoes` existentes; apenas registrar aviso.

#### `proventos/{evento_id}`

| Campo | Tipo | Semântica |
|---|---|---|
| `evento_id` | string | Igual ao ID do documento. |
| `ticker` | string | Uppercase. |
| `tipo_provento` | string | Um de `DIVIDENDO`, `JCP`, `RENDIMENTO`, `OUTRO`. |
| `data_com` | string | Obrigatória, ISO. |
| `data_ex` | string \| null | Pode ser `None`; no fallback Yahoo é igual a `data_com`. |
| `data_pagamento` | string \| null | Pode ser `None`; fallback Yahoo sempre `None`. |
| `valor_bruto` | float | Arredondado a 6 casas. |
| `fonte` | string | `"B3"`, `"Yahoo Finance (data ex como data_com)"` ou similar. |

### 4.3 `evento_id` determinístico

```python
def make_event_id(ticker: str, tipo_provento: str, data_com: str, valor_bruto: float) -> str:
    valor = round(float(valor_bruto), 6)
    raw = f"{ticker}_{tipo_provento}_{data_com}_{valor:.6f}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)
```

Exemplo: `ITUB4_DIVIDENDO_2024-05-20_0.450000`.

Testes obrigatórios:

- Mesmo evento gera o mesmo ID em execuções diferentes (RF-15/RNF-13).
- `0.45`, `0.4500000` e `"0.450"` geram `0.450000`.
- Caracteres inválidos (`/`, espaço, acento) viram `_`.

### 4.4 Índice composto

`firestore.indexes.json` com `collectionGroup` igual ao nome efetivo de proventos (`proventos` ou `{prefix}proventos`) e campos `ticker ASC, data_com ASC` (RF-21).

### 4.5 Invariantes de persistência

1. Toda escrita usa `merge=True`.
2. Nenhum batch excede 500 operações.
3. `pregoes` é sempre reescrito completo e ordenado.
4. `inicio_serie`/`fim_serie` nunca diminuem/aumentam incorretamente: usar `min`/`max` com o valor existente.
5. Reexecutar o mesmo lote não cria documento novo em `proventos` (mesmo `evento_id`).
6. Eventos não são apagados na v1.

---

## 5. Componentes e contratos

### 5.1 `src/utils/logging.py`

```python
def configure_logging(level: str = "INFO") -> None: ...
```

- Instala `StreamHandler` em `sys.stdout` com `JsonFormatter`.
- Cada linha é um JSON com `timestamp`, `level`, `logger`, `message`.
- Campos de `record.__dict__` que não são padrão são copiados para o JSON (padrão `extra={...}`).
- `timestamp` em UTC ISO 8601.
- `exc_info` vira `"exception"` com o traceback em string.
- Chamar `logging.basicConfig` uma única vez; `force=True` para testes.
- Nunca incluir `admin_token`, `b3_events_url`, headers ou corpos.

### 5.2 `src/utils/retry.py`

```python
T = TypeVar("T")

def retry(
    func: Callable[[], T],
    *,
    attempts: int,
    base_delay: float,
    retryable: tuple[type[Exception], ...],
    logger: logging.Logger | None = None,
    context: Mapping[str, object] | None = None,
) -> T: ...
```

Algoritmo:

1. Executa `func()`.
2. Se sucesso, retorna.
3. Se a exceção não estiver em `retryable`, propaga imediatamente.
4. Se `tentativa >= attempts`, propaga a última exceção.
5. Loga `retry` com `tentativa`, `tipo_erro` e `context` (ex.: `ticker`), sem payload.
6. Espera `base_delay * 2 ** (tentativa - 1)` com jitter uniforme de ±20% (`random.uniform(0.8, 1.2)`).

Matriz de retry:

| Origem | Repetir | Não repetir |
|---|---|---|
| HTTP | 429, 500, 502, 503, 504, timeout, `OSError` | demais 4xx |
| yfinance | `YFRateLimitError`, `TimeoutError`, `OSError`, exceções transitórias | `ValueError` de ticker inválido |
| Firestore | `ServiceUnavailable`, `DeadlineExceeded`, `InternalServerError`, `TooManyRequests`, `Aborted` | `PermissionDenied`, `NotFound`, `InvalidArgument`, `FailedPrecondition` |

`attempts` inclui a primeira tentativa: `attempts=3` = 1 execução + 2 retries.

### 5.3 `src/transformers/ticker.py`

```python
TICKER_PATTERN = re.compile(r"[A-Z0-9]{4}[0-9]{1,2}[A-Z]?F?")

def normalize_ticker(value: str) -> str: ...
```

- `value.strip().upper()`.
- `fullmatch` da regex; se falhar, `ValueError("Informe um ticker válido da B3, por exemplo BBAS3.")`.
- Mesma mensagem e padrão de `TickerService.validate` (RF-12); teste de paridade em §7.

### 5.4 `src/transformers/catalog.py`

```python
CATALOG_TYPES = frozenset({"STOCK", "UNIT"})

def catalog_tickers(path: str | Path = "data/ativos_b3.json") -> tuple[str, ...]: ...
```

- Abre JSON UTF-8; espera lista de objetos.
- Filtra `item.get("type") in CATALOG_TYPES` e `not item["ticker"].endswith("F")`.
- Deduplica, ordena e retorna tupla.
- Hoje retorna exatamente **376** tickers.
- Erros de arquivo/JSON propagam; `load_settings` converte em `ConfigurationError`.
- Teste de paridade obrigatório com `app.services.cash_yield_service.catalog_tickers()` (RF-03).

### 5.5 `src/transformers/quotes.py`

```python
def normalize_quotes(rows: Iterable[Mapping[str, object]]) -> list[Quote]: ...
def group_by_year(quotes: Iterable[Quote]) -> dict[int, list[Quote]]: ...
def merge_pregoes(existing: Iterable[Quote], new: Iterable[Quote]) -> list[Quote]: ...
```

`normalize_quotes`:

1. Para cada linha, exigir `data` e `close`; converter `data` com `parse_date`.
2. Converter `open`, `high`, `low`, `close`, `adj_close` com `_finite_float`; se algum for inválido, descartar a linha e logar `cotacao_invalida` com `data`.
3. `adj_close` ausente → `close`; `volume` ausente/`NaN` → `0`; `volume` negativo → `0`.
4. Deduplicar por `data`, mantendo a **última** ocorrência.
5. Ordenar por `data`.

`merge_pregoes`:

1. Mapa `{data: Quote}` com existentes.
2. Aplicar novos por cima (novo vence).
3. Retornar lista ordenada por `data`.

`group_by_year`: agrupa por `int(data[:4])`, preservando ordem.

### 5.6 `src/transformers/proventos.py`

```python
def parse_date(value: str | date | None) -> str | None: ...
def parse_brl_number(value: str | int | float | None) -> float | None: ...
def classify(raw_tipo: str | None) -> TipoProvento: ...
def make_event_id(ticker: str, tipo_provento: str, data_com: str, valor_bruto: float) -> str: ...
def normalize_events(rows: Iterable[Mapping[str, object]], ticker: str) -> list[EventoProvento]: ...
```

`parse_date`:

- `None`/string vazia → `None`.
- `date`/`datetime` → `.isoformat()[:10]`.
- Formatos aceitos: `YYYY-MM-DD`, `DD/MM/YYYY`, `YYYYMMDD`.
- Qualquer outro → `ValueError(f"Data inválida: {value!r}")` (RF-13).

`parse_brl_number`:

- `None`/vazio → `None`.
- `int`/`float` → valida finitude.
- String: remove `R$`, espaços e NBSP; remove parênteses tratando como negativo. Regras de separador:
  - contém `.` e `,` → remove `.` e troca `,` por `.` (ex.: `1.234,56` → `1234.56`);
  - contém só `,` → troca `,` por `.` (ex.: `1,5` → `1.5`);
  - contém só `.` → se houver exatamente 3 dígitos após o ponto e (mais de um ponto ou mais de 3 dígitos antes), trata como milhar e remove o ponto (`1.234` → `1234`); caso contrário, mantém como decimal (`0.45` → `0.45`).
- `NaN`, `inf`, texto inválido ou valor negativo → `ValueError` (RF-14).

`classify`:

1. Normaliza com `unicodedata.normalize("NFKD")`, remove acentos e aplica uppercase.
2. Contém `JCP` ou `JUROS SOBRE CAPITAL` → `JCP`.
3. Contém `DIVIDENDO` → `DIVIDENDO`.
4. Contém `RENDIMENTO` → `RENDIMENTO`.
5. Caso contrário → `OUTRO`.

`normalize_events`:

1. Normaliza ticker.
2. Para cada linha: `tipo_provento = classify(raw)`; `data_com = parse_date(...)`; se `data_com` for `None`, descartar e logar `provento_sem_data_com`.
3. `valor_bruto = parse_brl_number(...)`; se `None` ou `0`, descartar e logar `provento_sem_valor`.
4. `data_ex`/`data_pagamento` com `parse_date`; se `data_ex` ausente, `None`.
5. `fonte` padrão `"B3"` quando ausente.
6. Gerar `evento_id`; deduplicar por `evento_id` mantendo a última ocorrência.
7. Ordenar por `(data_com, evento_id)`.

### 5.7 `src/extractors/yfinance_quotes.py`

```python
def extract(ticker: str, start: str, end: str) -> list[Quote]: ...
```

- `ticker = normalize_ticker(ticker)`; símbolo `f"{ticker}.SA"`.
- Chamada, dentro de `retry(...)`:
  ```python
  yf.Ticker(symbol).history(
      start=start, end=end, auto_adjust=False, actions=False,
      progress=False, threads=False,
  )
  ```
- `end` é **exclusivo**; o pipeline envia `fim + 1 dia` (RF-07).
- DataFrame vazio ou `None` → `[]` (RF-08).
- Renomear colunas `Open/High/Low/Close/Adj Close/Volume`; `Adj Close` ausente → usar `Close`.
- Índice `DatetimeIndex` tz-aware ou naive → `Timestamp.date().isoformat()`.
- Linhas com `Close` ausente/`NaN` são descartadas por `normalize_quotes`.
- Retornar `normalize_quotes(rows)`.

### 5.8 `src/extractors/b3_cotahist.py`

```python
def extract(ticker: str, year: int, directory: str | Path) -> list[Quote]: ...
```

- Caminho: `{directory}/COTAHIST_A{year}.TXT`.
- Arquivo ausente → `[]` + `logger.warning("cotahist_ausente", extra={"ano": year})`.
- Ler com `encoding="latin-1"`, linha a linha.
- Considerar apenas registro tipo `01` (posições 1–2) e ticker nas posições 13–24 (`linha[12:24].strip()`).
- Layout posicional (1-based, arquivo de 245 caracteres):
  - data do pregão: `3–10` (`YYYYMMDD`)
  - preço de abertura: `57–63`
  - preço máximo: `64–70`
  - preço mínimo: `71–77`
  - preço último: `85–91`
  - quantidade de títulos negociados: `116–128`
- Preços têm 2 casas decimais implícitas: `int(campo) / 100`.
- `volume = int(campo_quantidade)`.
- `adj_close = close`; registrar aviso `adj_close_igual_close` uma vez por extração (RF-11).
- Linhas curtas ou numéricos inválidos são ignoradas.
- Retornar `normalize_quotes(rows)`.

### 5.9 `src/extractors/b3_events.py`

```python
class B3EventsError(RuntimeError): ...

class B3EventsPayloadParser:
    def parse(self, payload: object, ticker: str, start: str, end: str) -> list[dict]: ...

def extract(
    ticker: str,
    start: str,
    end: str,
    *,
    url: str,
    client: httpx.Client | None = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> list[EventoProvento]: ...
```

- `url` vazia → `[]` + `logger.warning("b3_events_sem_url")` (D7).
- `GET` com `params={"ticker": ticker, "dataInicio": start, "dataFim": end}`, timeout de 10 s.
- Retry em 429/5xx, timeout e `OSError`; qualquer outro erro HTTP ou JSON inválido → `B3EventsError`.
- `B3EventsPayloadParser` aceita:
  - lista de objetos; ou
  - envelope com `results`, `data` ou `eventos` contendo a lista.
- Aliases de campo aceitos: `ticker|codigo`, `tipo|tipoEvento|tipo_provento`, `dataCom|data_com`, `dataEx|data_ex`, `dataPagamento|data_pagamento`, `valor|valorBruto|valor_bruto`, `fonte`.
- Datas fora de `[start, end]` por `data_com` são descartadas.
- Retornar `normalize_events(rows, ticker)`.
- O parser é o único ponto que conhece o schema da B3; mudanças de layout ficam isoladas.
- **Pendência bloqueante de F1:** confirmar a URL e o schema reais antes de habilitar em produção (§11).

### 5.10 `src/extractors/yahoo_dividends.py`

```python
def extract(ticker: str, start: str, end: str) -> list[EventoProvento]: ...
```

- `yf.Ticker(f"{ticker}.SA").dividends` (série indexada por data ex).
- Filtrar `start <= data <= end`.
- Para cada evento:
  - `data_ex = data_com = data do índice` (limitação explícita);
  - `data_pagamento = None`;
  - `tipo_provento = "OUTRO"`;
  - `fonte = "Yahoo Finance (data ex como data_com)"`;
  - `valor_bruto = float(valor)`.
- Série vazia → `[]`.
- Retornar `normalize_events(rows, ticker)`.

### 5.11 `src/utils/dates.py`

```python
B3_TZ = timezone(timedelta(hours=-3))

def today_b3() -> date: ...
def full_window(today: date, years: int) -> tuple[date, date]: ...
def incremental_window(today: date, days: int) -> tuple[date, date]: ...
```

- `full_window`: `start = today.replace(year=today.year - years)`; se `today` for 29/02 e o ano destino não bissexto, usar 28/02.
- `incremental_window`: `start = today - timedelta(days=days)`.
- Ambas retornam `(start, end=today)`.
- `today_b3()` permite injeção de `today` nos testes via parâmetro das funções de janela; não usar `freezegun`.

### 5.12 `src/storage/firestore_client.py`

```python
def get_client(settings: MarketSettings | None = None) -> firestore.Client: ...
```

- `settings = settings or load_settings(resolve_adc_project=False)`.
- `credentials, default_project = google.auth.default()`.
- `project = settings.google_cloud_project or default_project`.
- `firestore.Client(project=project, database=settings.firestore_database, credentials=credentials)`.
- Importar `google.cloud.firestore` dentro da função para não exigir a dependência em testes de módulos que não persistem.
- Não capturar exceções de credencial; deixar o pipeline/API traduzir.

### 5.13 `src/storage/batch_writer.py`

```python
class BatchedWriter:
    def __init__(self, client, batch_size: int = 500) -> None: ...
    def set(self, reference, data: dict, *, merge: bool = True) -> None: ...
    def flush(self) -> None: ...
    def __enter__(self) -> "BatchedWriter": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
```

- `batch_size = min(500, max(1, batch_size))`.
- `set` com `merge=False` → `ValueError("Toda escrita deve usar merge=True.")`.
- Cada `set` acumula em `self._batch` e incrementa `self._ops`.
- Ao atingir `batch_size`, `flush()`.
- `flush()`: se `_ops == 0`, não faz nada; senão `retry(self._batch.commit, ...)` e cria novo batch.
- `__exit__`: faz flush apenas se `exc_type is None`; se houve exceção, não tenta commitar operações parciais.
- Expor `pending` (int) para testes.

### 5.14 `src/pipelines/market_pipeline.py`

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
    client=None,
    dry_run: bool = False,
) -> tuple[TickerResult, ...]: ...
```

Fluxo de `run`:

1. `settings = settings or load_settings(resolve_adc_project=not dry_run)`.
2. `universo = tickers or settings.tickers`; normalizar, deduplicar, preservar ordem.
3. `client` só é criado se `dry_run is False` (`get_client(settings)`).
4. `ThreadPoolExecutor(max_workers=settings.workers)` com `executor.map`, preservando a ordem dos resultados.
5. Retornar `tuple(results)`.

Fluxo de `_run_ticker(ticker, ...)`:

1. `ticker = normalize_ticker(ticker)`.
2. Janela conforme `modo`; `end_exclusivo = fim + 1 dia`.
3. **Cotações:** `yfinance_quotes.extract(ticker, inicio, end_exclusivo)`.
   - Se `cotahist_dir`: para cada ano de `inicio.year..fim.year`, extrair e unir com precedência para COTAHIST (oficial).
   - `quotes = merge_pregoes(yf_quotes, cotahist_quotes)`.
   - Se vazio: `logger.warning("sem_cotacoes", extra={"ticker": ticker})`.
4. **Proventos:**
   - Se `b3_events_url`: tentar `b3_events.extract`; em `B3EventsError`, logar `b3_events_falhou` e seguir para fallback.
   - Se B3 vazio ou indisponível: `yahoo_dividends.extract`; se retornar eventos, `logger.warning("yahoo_fallback", extra={"ticker": ticker})` (a API deriva o aviso da `fonte`).
   - Se ambos vazios: `logger.info("sem_proventos", extra={"ticker": ticker})`.
5. **Transformação:** `group_by_year(quotes)`.
6. **Leitura do existente (somente se não `dry_run`):**
   - `ativos/{ticker}` para metadados.
   - Para cada ano tocado, `cotacoes_anuais/{ano}`.
   - Documento inexistente → `{}`.
7. **Merge:** `merge_pregoes(existente, novo)` por ano.
8. **Metadados:**
   - `inicio_serie = min(datas de todos os pregões conhecidos)`; se não houver pregão novo, preservar o valor existente.
   - `fim_serie = max(...)`; mesma regra.
   - `ultimo_provento_em = max(metadado existente, maior data entre os eventos novos)`.
   - `quantidade_cotacoes`: `contador_existente + Σ(novo_total_ano - antigo_total_ano)` para os anos tocados; contador ausente = `0` (D4).
   - `quantidade_proventos`: `len(eventos_novos)` (D4).
9. **Escrita (se não `dry_run`):** `BatchedWriter` com `merge=True` para metadados, anos e eventos.
10. **Dry-run:** não ler nem escrever; logar `dry_run_ticker` com `cotacoes`, `proventos`, `anos`.
11. **Isolamento:** qualquer exceção → `logger.exception("ticker_falhou", extra={"ticker": ticker})`, `TickerResult` com `erros=(str(exc),)`, contadores zerados.
12. `duracao_ms` com `time.perf_counter()`.

Regras adicionais:

- Não escrever documento anual com lista vazia.
- Não apagar eventos nem anos.
- Se apenas proventos mudarem, atualizar `ultimo_provento_em` mesmo sem cotações novas.
- `atualizado_em` sempre atualizado quando há escrita.

### 5.15 `src/cli.py`

```python
def build_parser() -> argparse.ArgumentParser: ...
def main(argv: list[str] | None = None) -> int: ...
```

| Argumento | Default | Efeito |
|---|---|---|
| `--full` / `--incremental` | `--full` | Mutuamente exclusivos. |
| `--tickers` | env | CSV; sobrescreve `MARKET_TICKERS`. |
| `--catalog` | env | Ativa catálogo; vence `--tickers`. |
| `--catalog-path` | env | Caminho do catálogo. |
| `--tickers-file` | env | JSON/TXT. |
| `--years` | env | Só no full. |
| `--days` | env | Só no incremental. |
| `--cotahist-dir` | env | Diretório COTAHIST. |
| `--project` | env | Sobrescreve projeto. |
| `--database` | env | Sobrescreve banco. |
| `--workers` | env | Paralelismo. |
| `--dry-run` | `False` | Não escreve. |
| `--log-level` | `INFO` | Nível do log JSON. |

Implementação:

1. `configure_logging(args.log_level)`.
2. Montar `env = dict(os.environ)` e aplicar overrides dos argumentos (`MARKET_*`, `GOOGLE_CLOUD_PROJECT`, `FIRESTORE_DATABASE`).
3. `settings = load_settings(env=env, resolve_adc_project=not args.dry_run)`; `ConfigurationError` → log + `return 2`.
4. `results = run(modo=..., tickers=..., settings=settings, dry_run=args.dry_run)`.
5. Logar resumo `execucao_concluida` com `modo`, `tickers`, `falhas`, `duracao_ms`.
6. `return 1 if any(r.erros for r in results) else 0`.
7. `KeyboardInterrupt` → log + `return 1`.

### 5.16 `src/repositories/market_repository.py`

```python
def get_cotacoes(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    client=None,
    settings: MarketSettings | None = None,
) -> list[Quote]: ...

def get_proventos(
    ticker: str,
    start_date: str | None = None,
    *,
    client=None,
    settings: MarketSettings | None = None,
) -> list[EventoProvento]: ...
```

`get_cotacoes`:

1. `ticker = normalize_ticker(ticker)`.
2. `start = date.fromisoformat(start_date)`; `end = date.fromisoformat(end_date)`; erro → `ValueError("Data inválida: ...")`.
3. `start > end` → `ValueError("A data inicial não pode ser posterior à data final.")`.
4. `settings = settings or load_settings(resolve_adc_project=False)` (D1).
5. `client = client or get_client(settings)`.
6. Para cada ano em `range(start.year, end.year + 1)`: ler `ativos/{ticker}/cotacoes_anuais/{ano}`; ignorar se não existir.
7. Concatenar `pregoes`, filtrar `start_date <= data <= end_date` (comparação lexicográfica), ordenar por `data`.
8. Retornar lista de `Quote` (sem metadados).

`get_proventos`:

1. Normalizar ticker; validar `start_date` se informado; `settings = settings or load_settings(resolve_adc_project=False)`.
2. `client = client or get_client(settings)`; `collection = client.collection(collection_name(settings, "proventos"))`.
3. Query padrão:
   ```python
   query = collection.where(filter=FieldFilter("ticker", "==", ticker))
   if start_date:
       query = query.where(filter=FieldFilter("data_com", ">=", start_date))
   query = query.order_by("data_com")
   ```
   `FieldFilter` vem de `google.cloud.firestore_v1.base_query`.
4. Em `FailedPrecondition` (de `google.api_core.exceptions`): `logger.warning("indice_proventos_ausente")`; refazer sem filtro/ordem de `data_com`, filtrar e ordenar em Python (D6).
5. Converter cada documento em `EventoProvento`; se `evento_id` ausente, usar `doc.id`.
6. Retornar ordenado por `(data_com, evento_id)`.

Ambas as funções são somente leitura; não criam cache nem escrevem.

---

## 6. Contrato da API

### 6.1 `app/schemas/market.py`

```python
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

- `inicio`/`fim` são sempre preenchidos em respostas 200; o tipo opcional existe apenas por compatibilidade com a especificação técnica.
- Não adicionar campos obrigatórios novos sem atualizar PRD e testes.

### 6.2 Endpoint

```python
from src.config import load_settings
from src.repositories import market_repository

@router.get("/api/v1/market/{ticker}", response_model=MarketDataResponse)
def get_market_data(
    ticker: str,
    inicio: date | None = Query(default=None),
    fim: date | None = Query(default=None),
    incluir_cotacoes: bool = Query(default=True),
    incluir_proventos: bool = Query(default=True),
): ...
```

Ordem de validação (nesta exata sequência):

1. `ticker = ticker_service.validate(ticker)`; `ValueError` → **400** com a mensagem original. A resposta usa o ticker normalizado.
2. `market_settings = load_settings(resolve_adc_project=False)` (D1).
3. `fim_efetivo = fim or today_b3()`; `inicio_efetivo = inicio or fim_efetivo.replace(year=fim_efetivo.year - years)`, com guarda de 29/02 → 28/02.
4. `inicio_efetivo > fim_efetivo` → **400** `"A data inicial não pode ser posterior à data final."`.
5. `(fim_efetivo - inicio_efetivo).days > max_range_days` → **400** `"O intervalo máximo permitido é de 3650 dias."` (valor dinâmico).
6. Consultar apenas as seções solicitadas:
   - `incluir_cotacoes` → `market_repository.get_cotacoes(...)`.
   - `incluir_proventos` → `market_repository.get_proventos(...)`.
7. `ValueError` do repositório → **400** (defensivo).
8. Erros de Firestore/ADC → **503** com `"Não foi possível consultar o histórico de mercado no momento."`; nunca incluir detalhe de credencial, URL ou stack. Capturar `google.auth.exceptions.DefaultCredentialsError`, `google.api_core.exceptions.GoogleAPICallError` e `OSError`.

### 6.3 Avisos (mensagens exatas)

| Condição | Aviso |
|---|---|
| `incluir_cotacoes=True` e lista vazia | `"Nenhuma cotação encontrada para o período informado."` |
| `incluir_proventos=True` e lista vazia | `"Nenhum provento encontrado para o período informado."` |
| Ambos os conjuntos vazios | `"Nenhum dado encontrado para o período informado."` (adicional aos dois acima, quando aplicável) |
| Algum provento com `fonte` iniciando em `"Yahoo"` | `"Proventos obtidos do Yahoo Finance: data_com igual à data ex e data_pagamento indisponível."` |
| `incluir_cotacoes=False` | Não gerar aviso de cotações. |
| `incluir_proventos=False` | Não gerar aviso de proventos. |

- Avisos são strings únicas, na ordem da tabela, sem duplicatas.
- O aviso `"Nenhum dado encontrado..."` só é gerado quando pelo menos uma seção foi solicitada e ambas as seções solicitadas vieram vazias.
- Não expor `fonte` de cotações na resposta (o schema não tem esse campo).

### 6.4 Exemplo

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

### 6.5 Tabela de status

| Situação | Status | Corpo |
|---|---:|---|
| Dados encontrados | 200 | `MarketDataResponse`. |
| Sem dados | 200 | Listas vazias + avisos. |
| Ticker inválido | 400 | `{"detail": "Informe um ticker válido..."}`. |
| `inicio > fim` | 400 | `{"detail": "A data inicial não pode ser posterior à data final."}`. |
| Intervalo > limite | 400 | `{"detail": "O intervalo máximo permitido é de N dias."}`. |
| Data malformada | 422 | Validação do FastAPI (`date`). |
| Firestore/ADC indisponível | 503 | Mensagem genérica de §6.2. |

### 6.6 Integração em `app/api/routes.py`

- Importar `market_repository` como módulo (`from src.repositories import market_repository`) para permitir `monkeypatch.setattr(routes.market_repository, ...)`.
- Importar `load_settings` no módulo para permitir `monkeypatch.setattr(routes, "load_settings", ...)`.
- Não mover `market_repository` para dentro da função.
- O endpoint é registrado antes das rotas HTML, sem alterar as existentes.
- Nenhum `print`, nenhuma chamada a BRAPI/Yahoo no caminho da API.

---

## 7. Plano de testes

### 7.1 Infraestrutura de teste

Criar `app/tests/market_fakes.py` (sem prefixo `test_`, não coletado) com:

- `FakeSnapshot`: `exists`, `id`, `to_dict()`.
- `FakeDocumentReference`: `get()`, `set()`.
- `FakeCollection`: `document()`, `where()`, `order_by()`, `stream()`.
- `FakeQuery`: encadeamento de `where`/`order_by`, `stream()`.
- `FakeBatch`: `set()`, `commit()`, contador de operações.
- `FakeFirestoreClient`: `collection()`, `batch()`, dicionário interno `{caminho: dados}` e `write_count`.

Requisitos:

- Nenhum teste acessa rede, ADC ou Firestore real.
- yfinance é sempre mockado (`monkeypatch.setattr(yf, "Ticker", ...)` ou no módulo extrator).
- `httpx.MockTransport` para B3.
- `random.uniform` mockado quando o teste precisar de backoff determinístico.

### 7.2 `test_market_config.py`

| Caso | Esperado |
|---|---|
| Defaults do piloto | 4 tickers, `years=5`, `days=60`, `batch_size=500`. |
| `MARKET_TICKERS_FROM_CATALOG=true` | 376 tickers. |
| Precedência catálogo > `--tickers` | Catálogo vence. |
| `MARKET_TICKERS_FILE` TXT/JSON | Lista normalizada e sem duplicados. |
| `years=0`, `workers=0`, `retry_backoff=0` | `ConfigurationError` com mensagem específica. |
| `batch_size=999` | Ajustado para 500. |
| `resolve_adc_project=False` | Não chama `google.auth.default`. |
| `collection_name` | Aplica prefixo `MARKET_FIRESTORE_PREFIX` e fallback `FIRESTORE_PREFIX`. |

### 7.3 `test_market_transformers.py`

| Caso | Esperado |
|---|---|
| `normalize_ticker(" itub4 ")` | `ITUB4`. |
| `normalize_ticker("PETR")` | `ValueError` com a mesma mensagem de `TickerService`. |
| Paridade de regex | `normalize_ticker` e `TickerService.validate` aceitam/rejeitam a mesma lista. |
| `catalog_tickers()` | 376; igual a `CashYieldService.catalog_tickers()`. |
| `parse_date` | `2024-01-02`, `02/01/2024`, `20240102` → `2024-01-02`. |
| `parse_date("31/02/2024")` | `ValueError`. |
| `parse_brl_number("R$ 1.234,56")` | `1234.56`. |
| `parse_brl_number("1,5")` | `1.5`. |
| `parse_brl_number("1.234")` | `1234.0` (milhar). |
| `parse_brl_number("0.45")` | `0.45` (decimal). |
| `parse_brl_number("nan")` / `"inf"` | `ValueError`. |
| `classify` | `JCP`, `DIVIDENDO`, `RENDIMENTO`, `OUTRO`. |
| `make_event_id` | Determinístico e arredondado a 6 casas. |
| `normalize_quotes` | Dedupe por data, ordenação, `adj_close` fallback. |
| `merge_pregoes` | Novo sobrescreve data igual; antigas preservadas. |
| `normalize_events` | Dedupe por `evento_id`, ordenação por `data_com`. |

### 7.4 `test_market_extractors.py`

| Caso | Esperado |
|---|---|
| yfinance com DataFrame | Colunas renomeadas e `Quote` completo. |
| yfinance vazio | `[]`. |
| Chamada yfinance | `auto_adjust=False`, `actions=False`, `threads=False`; `end` repassado. |
| COTAHIST fixture | Preços divididos por 100, volume inteiro, `adj_close == close`. |
| COTAHIST arquivo ausente | `[]` + warning. |
| B3 via `MockTransport` | Payload mapeado para `EventoProvento`. |
| B3 500/timeout | `B3EventsError`. |
| B3 URL vazia | `[]` sem requisição. |
| Yahoo fallback | `data_com == data_ex`, `data_pagamento is None`, `tipo_provento == "OUTRO"`, `fonte` esperada. |

### 7.5 `test_market_storage.py`

| Caso | Esperado |
|---|---|
| 501 `set` | Dois commits (500 + 1). |
| `merge=False` | `ValueError`. |
| Exceção no `with` | Não faz flush. |
| `get_client` | Usa projeto/banco/credenciais de ADC mockado. |
| Retry Firestore | `ServiceUnavailable` repete; `PermissionDenied` não repete. |

### 7.6 `test_market_pipeline.py`

| Caso | Esperado |
|---|---|
| Janela full | 5 anos; 29/02 → 28/02. |
| Janela incremental | 60 dias. |
| Incremental | Preserva pregões antigos do mesmo ano. |
| Metadados | `min`/`max` e `ultimo_provento_em` corretos. |
| Falha em 1 ticker | Demais concluem; resultado com `erros`. |
| `dry_run=True` | `get_client` não é chamado; zero escritas. |
| Sem cotações | Não sobrescreve `pregoes` existentes. |
| Fallback B3→Yahoo | Eventos com `fonte` Yahoo. |

### 7.7 `test_market_repository.py`

| Caso | Esperado |
|---|---|
| Intervalo inclusivo | Datas fora de `[start, end]` excluídas. |
| Ano inexistente | Ignorado sem erro. |
| Ordenação | `cotacoes` por `data`, `proventos` por `data_com`. |
| `start_date=None` | Todos os proventos do ticker. |
| Índice ausente (`FailedPrecondition`) | Fallback em Python e mesmo resultado. |
| Ticker inválido / data inválida | `ValueError`. |

### 7.8 `test_market_api.py`

| Caso | Esperado |
|---|---|
| 200 | `cotacoes`, `proventos`, `avisos`. |
| Ticker inválido | 400. |
| `inicio > fim` | 400. |
| Intervalo > 3650 dias | 400. |
| Repositório lança erro de Firestore | 503 com mensagem genérica. |
| Listas vazias | 200 + avisos exatos. |
| `incluir_cotacoes=false` | Não chama `get_cotacoes`; sem aviso de cotações. |
| Fonte Yahoo | Aviso de fallback presente. |

### 7.9 `test_market_cli.py`

| Caso | Esperado |
|---|---|
| Sucesso | Exit `0`. |
| Um ticker com erro | Exit `1`. |
| Configuração inválida | Exit `2`. |
| `--dry-run` | `run` recebe `dry_run=True`; nenhum cliente. |
| `--catalog` | Universo de 376. |

### 7.10 Comandos de verificação

```bash
python -m pytest --cov=app --cov=src --cov-report=term-missing
node --test app/tests/test_ranking_ui.js app/tests/test_asset_search.js
```

Critério: todos os testes antigos passam sem alteração; cobertura nova cobre os casos acima; nenhum teste depende de ordem de execução.

---

## 8. Sequência de implementação

Cada fase é um incremento independente e aditivo. Nenhuma fase altera testes existentes.

### F0 — Fundação

Arquivos:

- `src/__init__.py`
- `src/config.py`
- `src/models.py`
- `src/utils/__init__.py`, `logging.py`, `dates.py`, `retry.py`
- `.env.example`
- `requirements.txt` (+ `google-auth>=2.0`)
- `firestore.indexes.json`

Saída: `load_settings` valida e resolve projeto/prefixo sem efeitos colaterais; retry e logging testados.

Gate: `test_market_config.py` e casos de retry verdes; `--dry-run` ainda não existe, mas nenhum import de `src` quebra `app`.

### F1 — Extração e transformação

Arquivos:

- `src/transformers/ticker.py`, `catalog.py`, `quotes.py`, `proventos.py`
- `src/extractors/yfinance_quotes.py`, `b3_cotahist.py`, `b3_events.py`, `yahoo_dividends.py`
- `test_market_transformers.py`, `test_market_extractors.py`

Saída: 376 tickers com paridade comprovada; cotações/proventos normalizados; fallback Yahoo funcional.

Gate: paridade `catalog_tickers()` × `CashYieldService.catalog_tickers()`; todos os extractors testados sem rede.

### F2 — Persistência e CLI

Arquivos:

- `src/storage/firestore_client.py`, `batch_writer.py`
- `src/pipelines/market_pipeline.py`
- `src/cli.py`
- `test_market_storage.py`, `test_market_pipeline.py`, `test_market_cli.py`

Saída: `--full`, `--incremental` e `--dry-run` idempotentes; falha isolada por ticker.

Gate: merge incremental preserva dias antigos; dry-run não cria cliente; exit codes 0/1/2.

### F3 — Leitura e API

Arquivos:

- `src/repositories/market_repository.py`
- `app/schemas/market.py`
- `app/api/routes.py` (endpoint aditivo)
- `test_market_repository.py`, `test_market_api.py`

Saída: `GET /api/v1/market/{ticker}` com 200/400/503 e avisos.

Gate: suíte completa (`app` + `src`) verde; contratos existentes inalterados.

### F4 — Operação

Arquivos:

- `Dockerfile`
- `docs/operacao-pipeline-mercado.md`
- `firestore.indexes.json` aplicado no ambiente

Saída: imagem única, Jobs `full`/`incremental`, índice composto e agendamento documentados.

Gate: outra pessoa reproduz deploy, carga e agendamento apenas com o runbook.

### F5 — Piloto e escala

1. `--full` com 4 tickers; inspeção no Console.
2. `--incremental` com 4 tickers.
3. `--full --catalog --dry-run` (376, sem escrita).
4. `--full --catalog` (376).
5. Reexecução para provar idempotência.
6. Validação do endpoint e coleta das métricas do PRD §3.2.

---

## 9. Rastreabilidade de aceite

| Critério do PRD §11 | Implementação | Teste |
|---|---|---|
| 1. Full cria ativo, anos e proventos | F2 pipeline + storage | `test_market_pipeline.py` |
| 2. Catálogo com 376 e sem escrita no dry-run | `catalog_tickers`, `run(dry_run=True)` | `test_market_transformers.py`, `test_market_pipeline.py` |
| 3. Idempotência de proventos | `make_event_id` + `merge=True` | `test_market_transformers.py`, `test_market_storage.py` |
| 4. `get_cotacoes` ordenado e filtrado | repository §5.16 | `test_market_repository.py` |
| 5. `get_proventos` por `data_com` | repository §5.16 | `test_market_repository.py` |
| 6. Incremental preserva antigos | `merge_pregoes` | `test_market_pipeline.py` |
| 7. Endpoint consolidado | §6 | `test_market_api.py` |
| 8. Fallback Yahoo com aviso | extractor + aviso §6.3 | `test_market_extractors.py`, `test_market_api.py` |
| 9. Logs sem segredo/URL/corpo | logging + retry | teste com `caplog`/`capsys` |
| 10. Pytest completo | — | comando §7.10 |
| 11. Node tests verdes | — | comando §7.10 |
| 12. Paridade do catálogo | §5.4 | `test_market_transformers.py` |
| 13. Endpoints existentes intactos | endpoint aditivo | suíte antiga |
| 14. Índice de proventos | §4.4 | teste de fallback + validação manual |
| 15. Jobs com `roles/datastore.user` | §10 | runbook |
| 16. Runbook reproduzível | §10 | revisão por outra pessoa |

Requisitos funcionais sem teste dedicado devem ser cobertos por teste de integração da fase correspondente; nenhum RF P0 pode ficar sem teste automatizado.

---

## 10. Operação

### 10.1 Dockerfile

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

- O Cloud Run Service usa o `CMD`.
- O Cloud Run Job sobrescreve os args: `--args="--full"` ou `--args="--incremental"`.
- `src/` e `data/` são obrigatórios na imagem.

### 10.2 Índice

```bash
gcloud firestore indexes composite create \
  --project=<PROJETO> \
  --collection-group=proventos \
  --field-config=field-path=ticker,order=ascending \
  --field-config=field-path=data_com,order=ascending
```

- Se `MARKET_FIRESTORE_PREFIX` estiver ativo, usar `{prefix}proventos` no `collection-group`.
- O fallback de §5.16 permite operar antes do índice, mas o caminho padrão deve ser o índice.

### 10.3 Jobs

```bash
gcloud run jobs create bazin-market-full \
  --image <IMAGEM> \
  --region <REGIAO> \
  --project <PROJETO> \
  --service-account <CONTA_DE_SERVICO> \
  --set-env-vars "MARKET_TICKERS_FROM_CATALOG=true,MARKET_WORKERS=2,MARKET_YEARS=5" \
  --args="--full" \
  --max-retries=2 \
  --task-timeout=60m

gcloud run jobs create bazin-market-incremental \
  --image <IMAGEM> \
  --region <REGIAO> \
  --project <PROJETO> \
  --service-account <CONTA_DE_SERVICO> \
  --set-env-vars "MARKET_TICKERS_FROM_CATALOG=true,MARKET_WORKERS=2" \
  --args="--incremental" \
  --max-retries=2 \
  --task-timeout=30m
```

Piloto: trocar `MARKET_TICKERS_FROM_CATALOG=true` por `MARKET_TICKERS=ITUB4,BBAS3,WEGE3,VALE3` e reduzir timeouts.

### 10.4 Agendamento

- Cloud Scheduler com OIDC para a conta de serviço que pode executar Jobs.
- Frequência recomendada: incremental diário após o fechamento da B3 (horário a confirmar — PRD §15).
- `--full` apenas em carga inicial ou reconstrução; não agendar rotineiramente.

### 10.5 Permissões

- `roles/datastore.user` para leitura/escrita no Firestore.
- Permissão de execução do Job (`roles/run.invoker` no Job, se acionado por Scheduler).
- Proibido `roles/owner` ou papéis de edição de IAM.

### 10.6 Conteúdo mínimo do runbook

1. Pré-requisitos (APIs, Firestore Native, conta de serviço).
2. Aplicação do índice.
3. Build e publicação da imagem.
4. Criação/atualização dos Jobs.
5. Carga inicial e validação no Console.
6. Agendamento e verificação do incremental.
7. Diagnóstico: 403, 404 de banco, 429 do yfinance, índice ausente.
8. Rollback: desabilitar Scheduler e reverter imagem.

---

## 11. Riscos e pendências

| Item | Impacto | Tratamento |
|---|---|---|
| URL/schema reais da B3 não confirmados | Alto para proventos oficiais | Bloqueante apenas para produção de F1; fallback Yahoo mantém a entrega funcional. Confirmar antes do piloto. |
| Rate limit do yfinance (429) | Médio | `MARKET_WORKERS=2`, retry com jitter, timeout de Job maior. |
| `data_pagamento` ausente no Yahoo | Médio | Aviso explícito na API e `fonte` rastreável. |
| Índice ausente no ambiente | Médio | Fallback documentado em §5.16. |
| Banco Firestore nomeado sem cota gratuita | Médio | Preferir `(default)`; documentar no runbook. |
| Prefixo diferente do índice | Médio | Ajustar `collection-group` ao prefixo efetivo. |
| Eventos removidos na fonte permanecem | Baixo | Documentado; `--prune` em v2. |
| Divergência futura da regex de ticker | Baixo | Teste de paridade; unificação em v2. |
| Windows sem `tzdata` | Baixo | Fuso fixo `UTC-03:00` (D8). |

Perguntas do PRD §15 que **não bloqueiam** a implementação: horário do incremental, staging com prefixo, owner de plantão, endpoint de ingest na v2, FIIs/ETFs e SLA de defasagem.

---

## 12. Checklist de conclusão

- [ ] `src/` criado conforme §3–§5, sem importar `app/`.
- [ ] `app/` importa apenas `src.config` e `src.repositories.market_repository`.
- [ ] `requirements.txt` inclui `google-auth>=2.0`.
- [ ] `.env.example`, `firestore.indexes.json`, `Dockerfile` e runbook criados.
- [ ] `README.md` atualizado com o endpoint e as variáveis `MARKET_*`.
- [ ] Catálogo retorna 376 e paridade comprovada.
- [ ] `--full`, `--incremental`, `--dry-run` e exit codes 0/1/2 implementados.
- [ ] `--dry-run` não cria cliente Firestore.
- [ ] Incremental preserva pregões antigos.
- [ ] `get_cotacoes`/`get_proventos` com contratos de §5.16.
- [ ] Endpoint aditivo com 200/400/503 e avisos exatos.
- [ ] Nenhum log contém token, chave, URL completa ou corpo de resposta.
- [ ] `python -m pytest --cov=app --cov=src --cov-report=term-missing` verde.
- [ ] `node --test app/tests/test_ranking_ui.js app/tests/test_asset_search.js` verde.
- [ ] Suíte antiga inalterada.
- [ ] `tarefa.md` e `data/ativos_b3.json` preservados.
