# Papel e Objetivo
Você é um Engenheiro de Dados e Cloud Sênior (GCP / Python / Firestore / Cloud Run) especializado em dados do mercado financeiro brasileiro (B3). Sua tarefa é criar um pipeline modular em Python para extrair os **últimos 5 anos** de histórico de ações (cotações diárias e eventos de proventos com data com, data ex, data de pagamento, tipo e valor) e persistir no **Google Cloud Firestore**, deixando a estrutura pronta para consumo por uma aplicação hospedada no **Google Cloud Run**.

# Requisitos Funcionais
1. **Janela Temporal:** Últimos 5 anos a partir da data de execução.
2. **Tickers:** Lista configurável via variável de ambiente ou arquivo de configuração (ex.: `ITUB4`, `BBAS3`, `WEGE3`, `VALE3`).
3. **Fontes de Dados (100% Gratuitas):**
   - **Cotações:** `yfinance` (com sufixo `.SA` e `auto_adjust=False`) para `open`, `high`, `low`, `close`, `adj_close` e `volume`, com suporte opcional a leitura local de `COTAHIST_A<ANO>.TXT` da B3.
   - **Proventos:** Extrator de eventos corporativos da B3 e/ou cruzamento de proventos para preencher:
     - `ticker` (string, ex.: `"ITUB4"`)
     - `tipo_provento` (`"DIVIDENDO"`, `"JCP"`, `"RENDIMENTO"` ou `"OUTRO"`)
     - `data_com` (string `YYYY-MM-DD`)
     - `data_ex` (string `YYYY-MM-DD` ou `None`)
     - `data_pagamento` (string `YYYY-MM-DD` ou `None`)
     - `valor_bruto` (float)
     - `fonte` (string)
4. **Persistência no Google Cloud Firestore (`google-cloud-firestore`):**
   - Usar `WriteBatch` respeitando o limite de 500 operações por batch.
   - Garantir **idempotência** com IDs determinísticos e `merge=True`.
   - Estrutura de coleções:
     - `ativos/{ticker}`: metadados do ativo (`ticker`, `atualizado_em`, `inicio_serie`, `fim_serie`, `ultimo_provento_em`).
     - `ativos/{ticker}/cotacoes_anuais/{ano}`: documento por ano (ex.: `2025`) contendo `ticker`, `ano` (int), `atualizado_em` e lista/mapa `pregoes` ordenado por `data` (`data`, `open`, `high`, `low`, `close`, `adj_close`, `volume`), mantendo cada documento bem abaixo de 1 MB.
     - `proventos/{evento_id}`: um documento por provento com `evento_id` determinístico (`f"{ticker}_{tipo_provento}_{data_com}_{valor_bruto:.6f}"`), campos tipados (`data_com`, `data_ex`, `data_pagamento`, `tipo_provento`, `valor_bruto`, `ticker`, `fonte`) e indexável para consultas da aplicação no Cloud Run.
   - Incluir o módulo `src/repositories/market_repository.py` com funções prontas para a aplicação do Cloud Run consultar:
     - `get_cotacoes(ticker: str, start_date: str, end_date: str)`
     - `get_proventos(ticker: str, start_date: str | None = None)`

# Requisitos Técnicos e de Integração com Cloud Run
- **Autenticação GCP:** Usar `google.auth.default()` / `firestore.Client(database=...)` sem credenciais hardcoded. Suportar `GOOGLE_CLOUD_PROJECT` e `FIRESTORE_DATABASE` via variáveis de ambiente.
- **Execução:** Compatível com execução local (`gcloud auth application-default login` / `GOOGLE_APPLICATION_CREDENTIALS`) e com **Cloud Run Jobs** ou endpoint HTTP no **Cloud Run**.
- **Modos de Execução:**
  - `--full`: carga histórica dos últimos 5 anos.
  - `--incremental`: atualiza apenas os últimos 60 dias de cotações e proventos recentes.
- **Resiliência:** *Retries* com *backoff* exponencial em chamadas externas e escrita no Firestore, logging estruturado e tratamento de falhas por ticker sem interromper o lote inteiro.

# Entregáveis Esperados
1. Árvore de pastas, `requirements.txt` e `.env.example`.
2. Código Python limpo, tipado (`type hints`) e modular (`config`, `extractors`, `transformers`, `storage/firestore_client.py`, `repositories/market_repository.py`, `cli.py`).
3. Exemplo de uso do `market_repository.py` dentro de um endpoint (ex.: FastAPI no Cloud Run) retornando cotações e proventos consolidados em JSON.