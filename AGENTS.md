# AGENTS.md — Instruções para agentes de código

Este arquivo resume o contexto do repositório **Preço Justo Bazin** e orienta qualquer agente (humano ou IA) que for trabalhar aqui. Leia antes de alterar código, documentação ou testes.

---

## 1. Como usar este arquivo

- Trate `tarefa.md`, `README.md` e `docs/` como fontes de verdade do comportamento esperado.
- Antes de editar, rode `git status --short --branch` e confirme a branch e o estado do working tree.
- Não sobrescreva arquivos do usuário sem confirmação, especialmente `tarefa.md` e `data/ativos_b3.json`.
- Documentação e comentários são em **português**; nomes de código seguem o padrão existente (funções/variáveis em inglês quando já estabelecido, domínio em português quando o código original usa, ex.: `preco_justo`).
- Prefira mudanças aditivas e compatíveis. A aplicação já tem contratos de API e testes que dependem de nomes e mensagens exatas.

---

## 2. Modo de comunicação — skill `caveman`

A skill `caveman` é obrigatória para as respostas ao usuário neste repositório.

- Arquivo: `skills/caveman/SKILL.md`. Registrada como fonte em `.opencode/opencode.json` (`"skills": ["./skills"]`), então o ID é **`caveman`**.
- Carregue com a ferramenta `skill` (ID `caveman`) no início da sessão, antes da primeira resposta. O modo fica **ativo em todas as respostas seguintes** até ser desligado.
- Nível padrão: **ultra**. Troque com `/caveman lite|full|ultra` (também existem `wenyan-lite`, `wenyan-full`, `wenyan-ultra`) quando o usuário pedir.
- O que muda: cortar artigos, fillers, cortesias e hedge; frases curtas e fragmentos são permitidos. **Toda a substância técnica permanece.**
- O que **não** muda: código, commits, PRs, mensagens de erro literais, nomes de funções/APIs e documentação do repositório. Esses continuam escritos normalmente e em **português**.
- Exceções de clareza (sai do modo e volta depois): avisos de segurança, confirmação de ação irreversível, sequências multi-passo em que a ordem fica ambígua e pedidos de esclarecimento.
- Desligar somente com `stop caveman` ou `normal mode`.

---

## 3. Visão geral da aplicação

Aplicação web em **FastAPI** que calcula o **preço justo de ações da B3 pelo Método de Bazin**, com:

- calculadora de valuation com memória de cálculo, gráficos e avisos;
- comparação de até 4 ativos, com preenchimento automático por pares setoriais;
- ranking opcional (desativado por padrão);
- seleção de até 30 ações por **cash-yield**;
- busca local de ativos com autocomplete;
- tema escuro/claro e layout responsivo.

Ponto de entrada: `app/main.py`. Router: `app/api/routes.py`.

### Endpoints atuais

| Endpoint | Finalidade |
|---|---|
| `GET /` e `GET /ranking` | Páginas HTML (mesmo template). |
| `GET /cash-yield` e `GET /gerarlista` | Páginas da seleção por cash-yield. |
| `GET /api/v1/assets` | Serve `data/ativos_b3.json`. |
| `GET /api/v1/valuation/{ticker}` | Valuation de um ativo. |
| `GET /api/v1/ranking` | Ranking (503 se `ENABLE_RANKING != true`). |
| `GET /api/v1/comparison` | Compara 1 a 4 tickers. |
| `GET /api/v1/cash-yield` | Estado da varredura de cash-yield. |
| `POST /api/v1/cash-yield/refresh` | Inicia varredura em background (202). |

---

## 4. Estrutura e responsabilidades

```text
app/
  main.py                 FastAPI + StaticFiles + router
  core/config.py          Settings via variáveis de ambiente
  api/routes.py           Endpoints, orchestração e templates
  models/                 Dataclasses frozen de domínio
  schemas/                Modelos Pydantic de request/response
  services/               Regras de negócio e accesso a fontes externas
  repositories/           SQLite e Firestore
  templates/              Jinja2 (index, cash_yield, cash_yield_update)
  static/                 CSS e JS (app.js, asset-search.js, cash-yield.js)
  tests/                  pytest + testes Node.js de UI
data/
  ativos_b3.json          Catálogo local (2.297 entradas)
  valuation_history.sqlite Não versionar/alterar sem necessidade
docs/
  configuracao-firestore.md
  especificacao-tecnica-pipeline-mercado.md   # plano aprovado, ainda não implementado
skills/
  caveman/SKILL.md        Skill de comunicação (ID `caveman`, obrigatória)
.opencode/
  opencode.json           Config do projeto; registra `./skills` como fonte
  agents/desenvolvedor.md
tarefa.md                 Pedido original do pipeline de mercado
```

### Convenções existentes

- `dataclasses(frozen=True)` para modelos de domínio.
- `Pydantic BaseModel` para contratos de API.
- Instâncias de serviços/repositórios criadas no nível do módulo em `app/api/routes.py` (`repository`, `ticker_service`, `valuation_service`, `sector_peer_service`, `cash_yield_service`). **Não mover para dentro das funções**: os testes fazem `monkeypatch.setattr(routes, ...)`.
- Helpers `_calculate()` e `_response()` em `routes.py` também são monkeypatchados nos testes; preservar assinatura.
- Concorrência com `ThreadPoolExecutor` para ranking/comparação; falhas por ticker viram avisos, não quebram o lote.
- Logs usam `extra={...}` com `ticker`, `provider`, `status_http`, `error_type`. **Nunca logar chave, token, URL completa ou corpo de resposta** — há testes que garantem que a palavra `segredo` não aparece em `caplog`.
- Ao alterar arquivos em `app/static/`, atualizar o parâmetro `?v=` no `<script>`/`<link>` do template correspondente para forçar cache busting.

---

## 5. Comandos

Requer Python 3.12+.

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Testes:

```bash
python -m pytest --cov=app --cov-report=term-missing
node --test app/tests/test_ranking_ui.js app/tests/test_asset_search.js
```

Após a implementação do pacote `src/`, o comando de cobertura passa a ser:

```bash
python -m pytest --cov=app --cov=src --cov-report=term-missing
```

Não há `.gitignore` no repositório. Evite adicionar `__pycache__`, `.pyc`, `data/valuation_history.sqlite`, `data/cash_yield_cache.json` ou `.env`. Alguns desses artefatos já existem no repositório; não remova sem confirmação.

---

## 6. Configuração por ambiente

Definidas em `app/core/config.py`:

| Variável | Default | Observação |
|---|---|---|
| `BAZIN_RATE` | `0.06` | Taxa padrão em decimal. |
| `DATABASE_PATH` | `data/valuation_history.sqlite` | SQLite local. |
| `BRAPI_API_KEY` | vazio | Nunca versionar. Sem chave, usa Yahoo como fallback. |
| `CASH_YIELD_CACHE_PATH` | `data/cash_yield_cache.json` | Lista pronta. |
| `CASH_YIELD_WORKERS` | `4` | Paralelismo da varredura. |
| `STORAGE_BACKEND` | `sqlite` | `firestore` ativa persistência remota. |
| `FIRESTORE_PROJECT` | vazio | Projeto do Firestore. |
| `FIRESTORE_PREFIX` | vazio | Prefixo das coleções `asset_cache`/`cash_yield`. |
| `ENABLE_RANKING` | `false` | Ranking desativado para reduzir consultas. |

`settings` é um dataclass congelado avaliado no import. Os testes substituem `routes.settings` com `SimpleNamespace`; mantenha esse padrão.

---

## 7. Regras de negócio críticas — não alterar sem atualizar testes e docs

1. **Taxa**: na API é decimal (`0.06` = 6%); na UI é porcentagem (`6`). Validação: `0 < taxa <= 1`.
2. **Períodos**: `ltm`, `3anos`, `5anos`, `todos` (default da API: `5anos`; default da UI: `3anos`).
   - `3anos`/`5anos`: anos civis encerrados; anos sem registro entram como zero e geram aviso.
   - `todos`: inclui anos retornados até o ano atual parcial, sem pagamentos futuros.
   - `ltm`: exige `pagamentos` com data; Yahoo só fornece data ex, portanto LTM é recusado nesse fallback.
3. **Dividend Yield**: sempre recalculado com dividendos do **último ano civil encerrado** ÷ preço atual, independente do período escolhido.
4. **Classificação** pela margem: `>30` Muito Barata, `>10` Barata, `-10..10` Justa, `-30..<-10` Cara, `<-30` Muito Cara. Limites são testados explicitamente.
5. **Resumo**: maior/menor anual e crescimento médio das variações anuais consecutivas; crescimento fica indisponível com lacunas/base zero. No LTM, estatísticas anuais não se aplicam.
6. **Valores atípicos** (>2,5× mediana dos demais anos) geram aviso, mas **não são removidos** da média.
7. **Cash-yield**: y1 dos três últimos anos encerrados ≥ 6 em todos, com dividendos pagos em todos; ordenação pelo menor y1 e, em empate, pelo y1 do último ano; API expõe no máximo **30** itens com `posicao` começando em 1. A varredura padrão usa o catálogo (376); `POST /api/v1/cash-yield/refresh?escopo=piloto` limita aos 4 tickers de `MARKET_TICKERS` e marca o resultado com aviso.
8. **Ranking**: tickers fixos `BBAS3, BBSE3, ITSA4, PETR4, TAEE11, CMIG4, TRPL4, SAPR4`; reordenar no front-end reusa dados carregados, sem novas consultas.
9. **Comparação**: 1 a 4 tickers, sem duplicados; clique no ticker da coluna recarrega a análise mantendo taxa e período.
10. **Pares setoriais**: lista curada em `app/services/sector_peer_service.py`; até 3 pares por ativo.
11. **Ticker**: validado por regex em `TickerService.validate` (`[A-Z0-9]{4}[0-9]{1,2}[A-Z]?F?`), aceitando códigos como `BBAS3F`, `A1LK34`, `03BK11`.
12. **Catálogo**: `data/ativos_b3.json` é um snapshot local usado no autocomplete e no universo do cash-yield; não garante cobertura completa. O recorte `STOCK`/`UNIT` sem sufixo `F` resulta em **376 ativos**.
13. **Interface**: valores/percentuais exibidos com 2 casas decimais, mas cálculos usam precisão original.

---

## 8. Armadilhas conhecidas

- BRAPI pode responder 401/403/429; logs devem informar `ticker` e `status_http`, sem expor a chave.
- Quando BRAPI não traz data de pagamento confirmada, o ano do evento pode derivar de data ex/data-com, com aviso; LTM pode ficar incompleto.
- Yahoo Finance fornece datas **ex-dividendo**, não datas de pagamento.
- `CashYieldService` roda varredura em thread dentro do serviço; no Cloud Run isso exige CPU sempre alocada (`--no-cpu-throttling` ou `min-instances=1`), que é o principal custo atual. **Não replique esse padrão no novo pipeline** — use Cloud Run Job.
- Banco Firestore nomeado (`FIRESTORE_DATABASE` diferente de `(default)`) **não** tem cota gratuita. Prefira `(default)`.
- `FIRESTORE_PREFIX` separa ambientes; o novo pipeline deve usar `MARKET_FIRESTORE_PREFIX` com fallback para ele.

---

## 9. Pipeline de mercado (implementado)

Fonte de verdade: `docs/especificacao-tecnica-pipeline-mercado.md` e `docs/SPEC-implementacao-pipeline-mercado.md`. Pedido original: `tarefa.md`.

### Status atual

- Pacote `src/` implementado: `config.py`, `models.py`, `cli.py`, `extractors/`, `transformers/`, `storage/`, `repositories/`, `pipelines/`, `utils/`.
- Endpoint aditivo `GET /api/v1/market/{ticker}` implementado em `app/api/routes.py`.
- Testes de mercado em `app/tests/test_market_*.py` e fakes em `app/tests/market_fakes.py`.
- `--dry-run` não cria cliente Firestore e não exige ADC.
- Piloto local validado com 4 tickers e com catálogo de 376 tickers (dry-run).
- Pendente de ambiente: aplicar `firestore.indexes.json`, rodar piloto real com ADC/Firestore, criar Jobs/Scheduler e confirmar URL/schema oficial da B3 (`MARKET_B3_EVENTS_URL`).
- Não alterar endpoints existentes para acomodar o pipeline; o novo endpoint é aditivo.

### O que foi decidido

- Pacote top-level `src/` com: `config.py`, `models.py`, `cli.py`, `extractors/`, `transformers/`, `storage/`, `repositories/`, `pipelines/`, `utils/`.
- Funções de leitura em `src/repositories/market_repository.py`:
  - `get_cotacoes(ticker, start_date, end_date)`
  - `get_proventos(ticker, start_date=None)`
- Coleções Firestore: `ativos/{ticker}`, `ativos/{ticker}/cotacoes_anuais/{ano}`, `proventos/{evento_id}`.
- `evento_id` determinístico: `f"{ticker}_{tipo_provento}_{data_com}_{valor_bruto:.6f}"`; arredondar valor em 6 casas antes de formatar/armazenar.
- Escrita sempre com `merge=True` e `WriteBatch` de no máximo 500 operações.
- Modos `--full` (5 anos) e `--incremental` (60 dias), com merge de `pregoes` por data para não apagar dias antigos.
- Autenticação somente via ADC (`google.auth.default()`); suporte a `GOOGLE_CLOUD_PROJECT` e `FIRESTORE_DATABASE`.
- Execução recomendada como **Cloud Run Job**; API expõe somente leitura via `GET /api/v1/market/{ticker}`.
- Universo configurável:
  - piloto: 4 tickers (`ITUB4,BBAS3,WEGE3,VALE3`);
  - produção: `--catalog` / `MARKET_TICKERS_FROM_CATALOG=true` → **376** `STOCK`/`UNIT`;
  - alternativas: `--tickers-file`, `--tickers`.
- Custo: com 4 ou 376 tickers, Firestore e Cloud Run permanecem dentro do free tier; o limitante é tempo/rate limit do yfinance, não dinheiro.
- Índice composto necessário em `proventos`: `(ticker ASC, data_com ASC)`.

### Ao alterar

1. Seguir a árvore e os contratos da especificação/SPEC.
2. Manter os testes de mercado, incluindo paridade entre `catalog_tickers()` e `CashYieldService.catalog_tickers()`.
3. Manter `google-auth>=2.0` em `requirements.txt`.
4. Manter `.env.example`, `firestore.indexes.json`, `Dockerfile`, `docker-entrypoint.sh` e `docs/operacao-pipeline-mercado.md`.
5. Rodar `python -m pytest --cov=app --cov=src --cov-report=term-missing` e os testes Node.
6. Atualizar `README.md` quando endpoint ou variável de ambiente mudar.

---

## 10. Checklist de "pronto"

- [ ] `git status` revisado; nenhum artefato ou segredo adicionado.
- [ ] Testes antigos continuam passando sem alteração de contrato.
- [ ] Novos testes cobrem o comportamento alterado.
- [ ] `README.md`/`docs/` atualizados quando o comportamento muda.
- [ ] Logs não contêm chave, token, URL ou corpo de resposta.
- [ ] Ranking continua desativado por padrão.
- [ ] Cache/SQLite/Firestore existentes não foram apagados sem necessidade.
- [ ] `tarefa.md` e `data/ativos_b3.json` preservados.
