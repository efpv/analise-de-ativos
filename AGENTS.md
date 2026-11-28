# AGENTS.md — Instruções Locais (Preço Justo Bazin)

> Contexto específico do repositório **Preço Justo Bazin**. Leia este documento juntamente com as regras globais do workspace em [`../../AGENTS.md`](file:///C:/Users/Erick/OneDrive/Documentos/ai-workspace/AGENTS.md).

---

## 1. Governança e Comunicação Global

Este projeto segue integralmente as regras do workspace central:
- **Comunicação**: Modo **`caveman ultra`** e **Execução Silenciosa** obrigatórios conforme definido no [`../../AGENTS.md`](file:///C:/Users/Erick/OneDrive/Documentos/ai-workspace/AGENTS.md).
- **Pre-flight**: Verifique `git status --short --branch` antes de qualquer alteração.
- **Convenções**: Segue [`../../rules/backend-python.md`](file:///C:/Users/Erick/OneDrive/Documentos/ai-workspace/rules/backend-python.md) para tipagem, dataclasses imutáveis e sanitização de logs.

---

## 2. Visão Geral da Aplicação

Aplicação web em **FastAPI** que calcula o **preço justo de ações da B3 pelo Método de Bazin**, com:
- Calculadora de valuation com memória de cálculo, gráficos e avisos;
- Comparação de até 4 ativos com preenchimento automático por pares setoriais;
- Ranking opcional (desativado por padrão via `ENABLE_RANKING=false`);
- Seleção de até 30 ações por **cash-yield**;
- Busca local de ativos com autocomplete (`data/ativos_b3.json`);
- Tema escuro/claro e layout responsivo.

Ponto de entrada: `app/main.py`. Router: `app/api/routes.py`.

### Endpoints Principais

| Endpoint | Finalidade |
|---|---|
| `GET /` e `GET /ranking` | Páginas HTML (mesmo template). |
| `GET /cash-yield` e `GET /gerarlista` | Páginas da seleção por cash-yield. |
| `GET /como-funciona` | Página explicativa: dados coletados, fontes e limites. |
| `GET /api/v1/assets` | Serve catálogo local (`data/ativos_b3.json`). |
| `GET /api/v1/valuation/{ticker}` | Valuation individual de um ativo. |
| `GET /api/v1/ranking` | Ranking (503 se `ENABLE_RANKING != true`). |
| `GET /api/v1/comparison` | Compara 1 a 4 tickers simultâneos. |
| `GET /api/v1/cash-yield` | Estado da varredura de cash-yield. |
| `POST /api/v1/cash-yield/refresh` | Inicia varredura em background (202). |
| `GET /api/v1/market/{ticker}` | Leitura do pipeline de mercado (Firestore). |

---

## 3. Estrutura e Convenções Técnicas Locais

```text
app/
  main.py                 FastAPI + StaticFiles + router
  core/config.py          Settings via variáveis de ambiente
  api/routes.py           Endpoints, orquestração e templates
  models/                 Dataclasses frozen de domínio
  schemas/                Modelos Pydantic de request/response
  services/               Regras de negócio e acesso a fontes externas
  repositories/           SQLite e Firestore
  templates/              Jinja2 (index, cash_yield, cash_yield_update)
  static/                 CSS e JS (app.js, asset-search.js, cash-yield.js)
  tests/                  pytest + testes Node.js de UI
data/
  ativos_b3.json          Catálogo local (2.297 entradas)
  valuation_history.sqlite Histórico local
src/                      Pipeline de mercado em nuvem (Cloud Run Job)
docs/                     Especificações e ADRs
```

### ⚠️ Armadilhas Específicas do Código e Testes
- **Serviços no nível do módulo**: Instâncias criadas no nível do módulo em `app/api/routes.py` (`repository`, `ticker_service`, `valuation_service`, etc.) **NÃO devem ser movidas para dentro das funções**. A suíte de testes existente depende de `monkeypatch.setattr(routes, ...)`.
- **Helpers monkeypatchados**: `_calculate()` e `_response()` em `routes.py` são monkeypatchados nos testes; preserve suas assinaturas.
- **Cache Busting Manual**: Ao alterar arquivos em `app/static/`, atualize o parâmetro `?v=` no template Jinja correspondente.
- **Não apagar sem confirmação**: `tarefa.md`, `data/ativos_b3.json`, `data/valuation_history.sqlite`.

---

## 4. Comandos Locais

Requer Python 3.12+.

```bash
# Execução da API
python -m uvicorn app.main:app --reload

# Testes automatizados com cobertura
python -m pytest --cov=app --cov=src --cov-report=term-missing
node --test app/tests/test_ranking_ui.js app/tests/test_asset_search.js
```

---

## 5. Regras de Negócio do Método de Bazin

1. **Taxa**: Na API é decimal (`0.06` = 6%); na UI é porcentagem (`6`). Validação: `0 < taxa <= 1`.
2. **Períodos**: `ltm`, `3anos`, `5anos`, `todos` (default da API: `5anos`; default da UI: `3anos`).
   - `3anos`/`5anos`: anos civis encerrados; anos sem registro entram como zero e geram aviso.
   - `todos`: inclui anos retornados até o ano atual parcial.
   - `ltm`: exige `pagamentos` com data (recusado no fallback Yahoo).
3. **Dividend Yield**: Sempre recalculado com dividendos do **último ano civil encerrado** ÷ preço atual.
4. **Classificação por Margem**: `>30%` Muito Barata, `>10%` Barata, `-10..10%` Justa, `-30..<-10%` Cara, `<-30%` Muito Cara.
5. **Valores Atípicos**: Anos com proventos `>2,5×` mediana dos demais anos geram aviso, mas **não são removidos** da média.
6. **Cash-yield**: `y1` dos três últimos anos encerrados `≥ 6%` em todos; limite máximo de **30 ativos**.
7. **Ranking**: Tickers fixos `BBAS3, BBSE3, ITSA4, PETR4, TAEE11, CMIG4, TRPL4, SAPR4`. Reordenação no frontend reusa dados carregados.
8. **Validação de Ticker**: Regex `[A-Z0-9]{4}[0-9]{1,2}[A-Z]?F?`.

---

## 6. Pipeline de Mercado & Nuvem

- **Armazenamento**: Firestore (coleções `ativos/{ticker}`, `cotacoes_anuais/{ano}`, `proventos/{evento_id}`).
- **`evento_id` determinístico**: `f"{ticker}_{tipo_provento}_{data_com}_{valor_bruto:.6f}"`.
- **Escrita em Lote**: Sempre com `merge=True` e `WriteBatch` de no máximo 500 operações.
- **Execução**: Projetado para rodar como **Cloud Run Job** (evita custo de CPU contínua do Cloud Run Service).
- **Provedores**: BRAPI e Yahoo Finance (atenção: Yahoo fornece data ex, não data de pagamento).
