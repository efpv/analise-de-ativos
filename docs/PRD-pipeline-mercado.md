# PRD — Pipeline de Dados de Mercado (B3 → Firestore)

**Versão:** 1.0
**Data:** 2026-11-26
**Status:** Proposto para implementação
**Owner:** Produto / Engenharia de Dados
**Documento técnico de referência:** [`docs/especificacao-tecnica-pipeline-mercado.md`](especificacao-tecnica-pipeline-mercado.md) (v1.0)
**Pedido original:** [`tarefa.md`](../tarefa.md)

> Este PRD descreve **o problema, o valor esperado e os requisitos de produto**. A especificação técnica continua sendo a fonte de verdade para árvore de pastas, assinaturas, contratos de Firestore e detalhes de implementação. Em caso de divergência, a especificação técnica prevalece no "como"; este PRD prevalece no "por quê" e no "o que é aceitável entregar".

---

## 1. Sumário executivo

O **Preço Justo Bazin** hoje consulta BRAPI/Yahoo Finance a cada análise. Não existe histórico estruturado de cotações e proventos: cada tela depende de disponibilidade, plano e latência de terceiros, e o cache atual guarda apenas o suficiente para o cash-yield.

Este PRD propõe um **pipeline de ingestão próprio** que baixa os últimos 5 anos de cotações diárias e eventos de proventos da B3, normaliza, persiste no **Google Cloud Firestore** e expõe leitura pronta para o Cloud Run. O resultado é uma aplicação que **deixa de depender de chamadas externas no caminho de leitura histórica**, ganha uma base auditável e habilita evoluções (backtest, tela de histórico, recálculo de y1 com preço da época).

A entrega é **aditiva**: nenhum endpoint, regra de negócio ou teste existente muda. O novo endpoint `GET /api/v1/market/{ticker}` convive com valuation, ranking, comparação e cash-yield.

---

## 2. Contexto e problema

### 2.1 Situação atual

| Aspecto | Hoje | Consequência |
|---|---|---|
| Fonte de cotações | BRAPI / Yahoo Finance, sob demanda | Latência e falha de terceiros afetam toda análise |
| Fonte de proventos | BRAPI / Yahoo Finance, sob demanda | `data_pagamento` ausente no Yahoo; LTM limitado |
| Persistência | SQLite local ou Firestore para `asset_cache` e `cash_yield` | Sem histórico de preços nem de eventos corporativos |
| Repetibilidade | Cada consulta refaz chamadas | Custo de rate limit e resultados não auditáveis |
| Cash-yield | Varredura em thread no serviço Cloud Run | Exige CPU sempre alocada — principal custo atual |

### 2.2 Problemas a resolver

1. **Dependência frágil de terceiros** no caminho de leitura de dados históricos.
2. **Ausência de histórico estruturado** de cotações e proventos — impossível auditar, comparar ou evoluir indicadores.
3. **Dados de proventos incompletos** (sem `data_pagamento` confiável em fallback).
4. **Padrão de execução caro** (thread em serviço web) que não deve ser replicado.

### 2.3 Por que agora

- O catálogo local (`data/ativos_b3.json`) e o recorte `STOCK`/`UNIT` (376 ativos) já existem e são estáveis.
- Firestore e Cloud Run Job cabem no free tier para o volume estimado — o limitante é rate limit, não custo.
- A aplicação já tem convenções maduras de configuração, logging e testes que o pipeline pode reaproveitar.

---

## 3. Objetivos e métricas de sucesso

### 3.1 Objetivos de produto

| # | Objetivo | Como medimos |
|---|---|---|
| O1 | Eliminar dependência externa na leitura histórica | 100% das leituras de `GET /api/v1/market/{ticker}` servidas pelo Firestore, sem chamada a BRAPI/Yahoo |
| O2 | Ter base histórica confiável e idempotente | Reexecutar `--full` não altera a contagem de documentos em `proventos` |
| O3 | Cobrir o universo relevante de ações | `--catalog` processa exatamente **376** tickers `STOCK`/`UNIT`, com paridade com `CashYieldService.catalog_tickers()` |
| O4 | Operar com custo zero no free tier | 0 ocorrências de cobrança por Firestore/Cloud Run no piloto e na carga completa |
| O5 | Isolar falhas e não degradar a API | Falha de 1 ticker não aborta o lote; endpoints existentes seguem com a mesma suíte verde |

### 3.2 Métricas de sucesso (pós-lançamento)

| Métrica | Baseline | Meta |
|---|---|---|
| Latência p95 de `GET /api/v1/market/{ticker}` (5 anos) | n/a | < 1,5 s |
| Consultas externas por leitura de histórico | 2+ (BRAPI + Yahoo) | 0 |
| Cobertura de tickers do catálogo no `--full` | 0 | 376/376 (com falhas registradas, se houver) |
| Idempotência em reexecução | n/a | 0 documentos duplicados |
| Taxa de tickers com falha isolada no full | n/a | < 5% (alertar acima disso) |
| Custo mensal de infraestrutura | CPU sempre alocada (cash-yield) | R$ 0 no free tier |

### 3.3 Não-objetivos de sucesso

- Não é meta substituir o cache de cash-yield nesta entrega.
- Não é meta garantir 100% de `data_pagamento` — o fallback é explicitamente sinalizado.

---

## 4. Público-alvo e personas

| Persona | Necessidade | Como o pipeline atende |
|---|---|---|
| **Usuário da aplicação** (investidor) | Análise rápida e estável, mesmo se a fonte externa falhar | Leitura de histórico pelo Firestore, com avisos claros |
| **Desenvolvedor da aplicação** | Consumir dados sem reimplementar regras | `market_repository.py` com `get_cotacoes` / `get_proventos` |
| **Engenheiro de dados / operações** | Rodar carga inicial e incremental com segurança | CLI (`--full`/`--incremental`), Cloud Run Job, logs JSON, exit codes |
| **Analista de produto** | Confiar nos números e explicar divergências | Estrutura auditável, `fonte` por evento, `avisos` na resposta |

---

## 5. Escopo

### 5.1 Dentro do escopo (v1)

- Extração de cotações dos últimos 5 anos via `yfinance` (`.SA`, `auto_adjust=False`), com leitura opcional de `COTAHIST_A<ANO>.TXT`.
- Extração de proventos via eventos corporativos da B3, com fallback limitado do Yahoo Finance.
- Normalização, deduplicação e IDs determinísticos.
- Persistência no Firestore: `ativos/{ticker}`, `ativos/{ticker}/cotacoes_anuais/{ano}`, `proventos/{evento_id}`.
- Modos `--full` e `--incremental` (60 dias) com merge de pregões.
- CLI com `--catalog`, `--tickers`, `--tickers-file`, `--dry-run`.
- Repositório de leitura e endpoint `GET /api/v1/market/{ticker}`.
- Dockerfile único, `.env.example`, `firestore.indexes.json` e runbook de operação.
- Testes automatizados (pytest + suíte Node existente preservada).

### 5.2 Fora do escopo (v1)

| Item | Motivo | Evolução |
|---|---|---|
| `POST /api/v1/market/ingest` | Risco de escrita pública | v2, protegido por token/IAM |
| `--prune` de eventos removidos na fonte | Baixo impacto imediato | v2 |
| FIIs, ETFs e BDRs | Regras de proventos distintas | v2 |
| Tela web de histórico | Endpoint JSON já habilita | v2 |
| Substituição do cache de cash-yield | Requer preço histórico da época | v2+ |
| Classificação automática de JCP vs dividendo | Fonte não informa tipo | v2 |
| Unificação da regex de ticker (`TickerService` → `src`) | Refactor não bloqueante | v2 |

---

## 6. Histórias de usuário

### 6.1 Operação de dados

- **US-01** — Como engenheiro de dados, quero rodar `python -m src.cli --full` e ter os últimos 5 anos persistidos, para popular a base inicial.
- **US-02** — Como engenheiro de dados, quero rodar `--incremental` diariamente e atualizar só os últimos 60 dias, sem apagar pregões antigos.
- **US-03** — Como engenheiro de dados, quero `--catalog --dry-run` para validar os 376 tickers sem escrever nada.
- **US-04** — Como engenheiro de dados, quero que a falha de um ticker seja registrada e o lote continue, para não perder a carga inteira.
- **US-05** — Como engenheiro de dados, quero logs JSON com ticker, modo, contagens e duração, sem segredos.

### 6.2 Consumo pela aplicação

- **US-06** — Como desenvolvedor, quero `get_cotacoes(ticker, start, end)` retornando pregões ordenados no intervalo, para montar séries.
- **US-07** — Como desenvolvedor, quero `get_proventos(ticker, start_date)` filtrando por `data_com`, para calcular dividendos.
- **US-08** — Como usuário, quero `GET /api/v1/market/ITUB4` com cotações, proventos e avisos, para consultar o histórico consolidado.
- **US-09** — Como usuário, quero receber `avisos` explícitos quando o fallback Yahoo for usado (sem `data_pagamento`), para não confiar em dado incompleto sem saber.

### 6.3 Governança

- **US-10** — Como responsável de segurança, quero que nenhuma credencial, token, URL completa ou corpo de resposta apareça em logs ou respostas de API.

---

## 7. Requisitos funcionais

Prioridade: **P0** = bloqueante da v1; **P1** = necessário para operação confiável; **P2** = desejável.

### 7.1 Configuração e universo

| ID | Requisito | Prioridade |
|---|---|---|
| RF-01 | Universo selecionável por precedência: catálogo (`MARKET_TICKERS_FROM_CATALOG`/`--catalog`) → `MARKET_TICKERS_FILE` → `MARKET_TICKERS` → erro de configuração. | P0 |
| RF-02 | `catalog_tickers()` lê `data/ativos_b3.json`, filtra `type in {"STOCK","UNIT"}` e exclui sufixo `F`, retornando **376** tickers ordenados. | P0 |
| RF-03 | Deve existir teste de paridade entre `catalog_tickers()` e `CashYieldService.catalog_tickers()`. | P0 |
| RF-04 | `batch_size` limitado a 500 (ajusta com aviso se maior); `years > 0`, `incremental_days > 0`, `max_retries >= 0`, `workers >= 1`. | P1 |
| RF-05 | Projeto Firestore resolvido por `GOOGLE_CLOUD_PROJECT` → `FIRESTORE_PROJECT` → projeto ADC. | P1 |
| RF-06 | Prefixo de coleção: `MARKET_FIRESTORE_PREFIX` com fallback para `FIRESTORE_PREFIX`. | P1 |

### 7.2 Extração

| ID | Requisito | Prioridade |
|---|---|---|
| RF-07 | Cotações via `yfinance` com sufixo `.SA`, `auto_adjust=False`, `actions=False`, `threads=False`; `end` exclusivo (pipeline envia `fim + 1 dia`). | P0 |
| RF-08 | DataFrame vazio retorna lista vazia, sem exceção. | P1 |
| RF-09 | Leitura opcional de `COTAHIST_A<ANO>.TXT` (registro `01`, layout posicional de 245 bytes), preenchendo/substituindo datas do arquivo local. | P1 |
| RF-10 | Proventos via B3; se falhar ou vier vazio, fallback Yahoo com `data_com = data_ex`, `data_pagamento = None`, `tipo_provento = "OUTRO"` e aviso. | P0 |
| RF-11 | `adj_close = close` quando COTAHIST não tiver fator de ajuste, com aviso registrado. | P1 |

### 7.3 Transformação e persistência

| ID | Requisito | Prioridade |
|---|---|---|
| RF-12 | `normalize_ticker` aplica trim/uppercase e a mesma regex de `TickerService.validate`. | P0 |
| RF-13 | Datas aceitas em `YYYY-MM-DD`, `DD/MM/YYYY` e `YYYYMMDD`, sempre normalizadas para ISO. | P0 |
| RF-14 | Valores em BRL (`R$ 1.234,56`) parseados corretamente; `NaN`/`inf` rejeitados. | P0 |
| RF-15 | `evento_id = f"{ticker}_{tipo}_{data_com}_{valor_bruto:.6f}"`, com `round(valor, 6)` antes de formatar. | P0 |
| RF-16 | Toda escrita usa `merge=True` e `WriteBatch` de no máximo 500 operações. | P0 |
| RF-17 | Documento anual `pregoes` ordenado por `data`; no incremental, união por data preservando dias antigos. | P0 |
| RF-18 | Metadados `inicio_serie`/`fim_serie` usam `min`/`max` com o existente; `ultimo_provento_em` é o maior entre datas dos eventos. | P1 |
| RF-19 | Isolamento de falha por ticker; erros inesperados logados com `ticker` e sem payload. | P0 |

### 7.4 Leitura e API

| ID | Requisito | Prioridade |
|---|---|---|
| RF-20 | `get_cotacoes(ticker, start, end)` valida ISO e `start <= end` (`ValueError`), ignora anos inexistentes, filtra intervalo inclusivo e ordena por `data`. | P0 |
| RF-21 | `get_proventos(ticker, start_date=None)` consulta por ticker, filtra `data_com >= start_date` quando informado e ordena por `data_com`. | P0 |
| RF-22 | `GET /api/v1/market/{ticker}` retorna `MarketDataResponse` com `ticker`, `inicio`, `fim`, `cotacoes`, `proventos`, `avisos`. | P0 |
| RF-23 | Ticker inválido → 400; `inicio > fim` → 400; intervalo > `MARKET_MAX_RANGE_DAYS` (3650) → 400. | P0 |
| RF-24 | Datas omitidas → `fim = hoje`, `inicio = hoje - years`. | P1 |
| RF-25 | Erro de Firestore/ADC → 503 com mensagem genérica, sem detalhes de credencial/URL. | P0 |
| RF-26 | Sem dados no período → 200 com listas vazias e aviso. | P1 |

### 7.5 Operação

| ID | Requisito | Prioridade |
|---|---|---|
| RF-27 | CLI com `--full`/`--incremental`, `--tickers`, `--catalog`, `--catalog-path`, `--tickers-file`, `--years`, `--days`, `--cotahist-dir`, `--project`, `--database`, `--workers`, `--dry-run`, `--log-level`. | P0 |
| RF-28 | Exit codes: `0` sucesso, `1` falha parcial, `2` erro de configuração. | P1 |
| RF-29 | `--dry-run` executa extração/transformação e loga contagens sem escrever. | P0 |
| RF-30 | Runbook `docs/operacao-pipeline-mercado.md` com criação de Jobs, permissões, ordem de deploy e agendamento. | P1 |

---

## 8. Requisitos não funcionais

| ID | Categoria | Requisito |
|---|---|---|
| RNF-01 | Segurança | Autenticação **somente** via ADC (`google.auth.default()`); nenhuma credencial hardcoded. |
| RNF-02 | Segurança | Logs e respostas nunca contêm `BRAPI_API_KEY`, `MARKET_ADMIN_TOKEN`, URL completa ou corpo de resposta. |
| RNF-03 | Segurança | Conta de serviço com `roles/datastore.user`; proibido `roles/owner` ou papéis de edição de IAM. |
| RNF-04 | Resiliência | Backoff exponencial com jitter (±20%) em 429/5xx, timeout, `OSError` e erros transitórios do Firestore. |
| RNF-05 | Resiliência | **Não** repetir `PermissionDenied`, `NotFound`, `InvalidArgument` ou 4xx (exceto 429). |
| RNF-06 | Desempenho | Documento anual ~45 KB (≈250 pregões); muito abaixo do limite de 1 MB. |
| RNF-07 | Desempenho | `--full` de 376 tickers entre 20 e 60 min; incremental entre 5 e 30 min. |
| RNF-08 | Custo | Firestore e Cloud Run dentro do free tier em ambos os universos (4 e 376). |
| RNF-09 | Compatibilidade | Python 3.12+, `dataclasses` frozen, type hints, Pydantic v2, `httpx`, `yfinance`, `google-cloud-firestore`. |
| RNF-10 | Observabilidade | Logging JSON por linha com `timestamp`, `level`, `logger`, `message` e extras via `extra={...}`. |
| RNF-11 | Manutenibilidade | Nenhuma regra de negócio existente alterada; novos testes não modificam testes antigos. |
| RNF-12 | Portabilidade | Execução local (`gcloud auth application-default login` ou `GOOGLE_APPLICATION_CREDENTIALS`), Cloud Run Job e endpoint somente leitura. |
| RNF-13 | Idempotência | Reexecutar `--full` ou `--incremental` não duplica documentos nem cria eventos repetidos. |

---

## 9. Modelo de dados (visão de produto)

### 9.1 Entidades

| Entidade | O que representa | Chave |
|---|---|---|
| **Ativo** | Metadados e cobertura temporal de um ticker | `ativos/{ticker}` |
| **Cotação anual** | Pregões de um ano, ordenados por data | `ativos/{ticker}/cotacoes_anuais/{ano}` |
| **Provento** | Evento corporativo (dividendo, JCP, rendimento) | `proventos/{evento_id}` |

### 9.2 Campos esperados pelo produto

- **Cotação:** `data`, `open`, `high`, `low`, `close`, `adj_close`, `volume`.
- **Provento:** `evento_id`, `ticker`, `tipo_provento`, `data_com`, `data_ex`, `data_pagamento`, `valor_bruto`, `fonte`.
- **Ativo:** `ticker`, `atualizado_em`, `inicio_serie`, `fim_serie`, `ultimo_provento_em`, contadores opcionais.

### 9.3 Regras de qualidade

- Datas sempre `YYYY-MM-DD` (comparação lexicográfica).
- `data_com` sempre presente; `data_ex`/`data_pagamento` podem ser `None`, com aviso quando derivados.
- `valor_bruto` arredondado a 6 casas antes do `evento_id` e da escrita.
- Nenhum evento é apagado automaticamente na v1.

---

## 10. Experiência de uso

### 10.1 CLI

```bash
python -m src.cli --full                                  # piloto: 4 tickers
python -m src.cli --incremental                           # piloto
python -m src.cli --full --catalog                        # produção: 376 ativos
python -m src.cli --incremental --catalog --workers 2     # diário
python -m src.cli --full --tickers ITUB4,BBAS3 --dry-run
python -m src.cli --full --tickers-file ./meus_tickers.txt
```

### 10.2 API

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

### 10.3 Mensagens e estados

| Situação | Comportamento esperado |
|---|---|
| Sem dados no período | 200, listas vazias, aviso explicando |
| Fallback Yahoo usado | 200, aviso sobre `data_com`/`data_pagamento` |
| Ticker inválido | 400, mensagem de validação |
| Intervalo inválido/excessivo | 400, mensagem clara |
| Firestore/ADC indisponível | 503, mensagem genérica (sem credencial/URL) |
| Falha em 1 ticker no lote | Lote continua; exit code 1; erro logado |

---

## 11. Critérios de aceite

### 11.1 Funcionais

1. `MARKET_TICKERS=ITUB4 python -m src.cli --full` cria `ativos/ITUB4`, `ativos/ITUB4/cotacoes_anuais/{2021..2026}` e documentos em `proventos` com todos os campos tipados.
2. `python -m src.cli --full --catalog --dry-run` processa exatamente **376** tickers `STOCK`/`UNIT`, com falha isolada e **sem escrita**.
3. Rodar o mesmo comando duas vezes mantém a contagem de documentos em `proventos` inalterada (idempotência).
4. `get_cotacoes("ITUB4", "2024-01-01", "2024-12-31")` retorna lista ordenada com todos os campos e sem datas fora do intervalo.
5. `get_proventos("ITUB4", "2023-01-01")` retorna somente eventos com `data_com >= 2023-01-01`.
6. `--incremental` atualiza os últimos 60 dias **sem remover** pregões anteriores do mesmo ano.
7. `GET /api/v1/market/ITUB4` devolve JSON consolidado com `cotacoes`, `proventos` e `avisos`.
8. Falha simulada da B3 aciona fallback Yahoo com aviso explícito sobre `data_com`/`data_pagamento`.

### 11.2 Segurança e qualidade

9. Nenhum log contém token, chave, URL de requisição ou corpo de resposta.
10. `python -m pytest --cov=app --cov=src --cov-report=term-missing` passa, incluindo todos os testes antigos.
11. `node --test app/tests/test_ranking_ui.js app/tests/test_asset_search.js` continua verde.
12. Paridade `catalog_tickers()` × `CashYieldService.catalog_tickers()` comprovada por teste.
13. Nenhum endpoint existente (valuation, ranking, comparison, cash-yield) muda de contrato.

### 11.3 Operacionais

14. `firestore.indexes.json` aplicado e índice composto de `proventos` funcionando (ou fallback documentado em uso).
15. Cloud Run Job `--full` e `--incremental` executam com `roles/datastore.user` e ADC.
16. Runbook permite que outra pessoa reproduza deploy, carga e agendamento sem consultar o autor.

---

## 12. Plano de entrega

| Fase | Escopo | Critério de saída |
|---|---|---|
| **F0 — Fundação** | `src/config.py`, `models.py`, `utils/`, `.env.example`, `requirements.txt`, `firestore.indexes.json` | Config carrega, valida e resolve projeto/prefixo; testes de config |
| **F1 — Extração e transformação** | `extractors/`, `transformers/` | Cotações e proventos normalizados; 376 tickers do catálogo; paridade comprovada |
| **F2 — Persistência** | `storage/`, `pipelines/`, `cli.py` | `--full`/`--incremental`/`--dry-run` idempotentes; falha isolada |
| **F3 — Leitura e API** | `repositories/`, `schemas/market.py`, endpoint | `GET /api/v1/market/{ticker}` com 200/400/503 corretos |
| **F4 — Operação** | `Dockerfile`, runbook, Jobs, agendamento | Deploy reproduzível e incremental diário |
| **F5 — Piloto e escala** | 4 tickers → 376 tickers | Métricas de §3.2 coletadas |

### 12.1 Estratégia de validação

1. Testes unitários por módulo (transformers, extractors, storage, pipeline, repository, API).
2. `--dry-run` no piloto (4 tickers) e no catálogo (376).
3. Carga real no piloto, inspeção manual no Console do Firestore.
4. Carga completa e validação do endpoint.
5. Reexecução para provar idempotência.

---

## 13. Riscos e mitigação

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Rate limit do yfinance (429) no universo completo | Alta | Médio | `MARKET_WORKERS=2`, retry com jitter, timeout de Job maior |
| Mudança no schema da consulta de eventos da B3 | Média | Alto | Parser isolado em `B3EventsPayloadParser`; fallback Yahoo |
| `data_pagamento` ausente no fallback | Alta | Médio | Aviso explícito na API e nos logs |
| Índice composto ausente no ambiente | Média | Médio | Fallback de filtro em Python documentado |
| Custo inesperado no Firestore | Baixa | Médio | Free tier validado; monitorar contagem de escritas |
| Banco Firestore nomeado sem cota gratuita | Baixa | Médio | Preferir `(default)`; documentar |
| Divergência de regex de ticker entre app e pipeline | Média | Baixo | Teste de paridade; unificação planejada para v2 |
| Eventos removidos na fonte permanecem no banco | Média | Baixo | Documentado; `--prune` em v2 |

---

## 14. Dependências

- Python 3.12+, `yfinance`, `httpx`, `google-cloud-firestore`, `google-auth` (explícita).
- Firestore em modo Native e conta de serviço com `roles/datastore.user`.
- Catálogo `data/ativos_b3.json` preservado (376 ativos `STOCK`/`UNIT`).
- Cloud Run Job + Cloud Scheduler (OIDC) para operação diária.
- `docs/configuracao-firestore.md` como base de permissões.

---

## 15. Perguntas abertas

1. O incremental diário será agendado em horário fixo após o fechamento da B3? Qual fuso de referência?
2. Haverá ambiente de staging com prefixo Firestore separado (`MARKET_FIRESTORE_PREFIX`)?
3. Quem é o owner de plantão para falhas de Job (alerta por e-mail, Slack ou Cloud Monitoring)?
4. A v2 deve incluir `POST /api/v1/market/ingest` ou manter apenas Job?
5. FIIs/ETFs entram no próximo ciclo? Isso exige revisar `RENDIMENTO` e `tipo_provento`.
6. Qual o SLA aceitável de defasagem do incremental (D+0, D+1)?

---

## 16. Rastreabilidade

| Seção do PRD | Origem na especificação técnica |
|---|---|
| §3 Objetivos | §1 Contexto, §2.2 Universo, §11 Critérios de aceite |
| §5 Escopo | §2 Decisões, §12 Fora de escopo |
| §7 Requisitos funcionais | §4 Configuração, §5 Contratos, §6 Componentes |
| §8 Requisitos não funcionais | §6.1 Retry, §6.2 Logging, §9 Resiliência |
| §9 Modelo de dados | §5.2 Firestore |
| §10 Experiência | §6.8 CLI, §7.2 Endpoint |
| §11 Critérios de aceite | §11 Critérios de aceite |
| §12 Plano de entrega | §3 Árvore, §8 Execução, §10 Testes |
| §13 Riscos | §9 Resiliência, §12 Evoluções |

---

## 17. Anexos

- Especificação técnica completa: [`docs/especificacao-tecnica-pipeline-mercado.md`](especificacao-tecnica-pipeline-mercado.md)
- Configuração do Firestore: [`docs/configuracao-firestore.md`](configuracao-firestore.md)
- Pedido original: [`tarefa.md`](../tarefa.md)
- Convenções do repositório: [`AGENTS.md`](../AGENTS.md)
