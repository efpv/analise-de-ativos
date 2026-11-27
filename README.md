# Preço Justo Bazin

Aplicação web em FastAPI para calcular o preço justo de ações da B3 pelo Método de Bazin, com memória de cálculo, análise de dividendos, ranking e comparação de ativos.

## Execução

Requer Python 3.12 ou superior. No terminal Bash:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Acesse `http://127.0.0.1:8000` e consulte a documentação em `http://127.0.0.1:8000/docs`.
O ranking está temporariamente desativado por padrão para reduzir consultas às fontes. Para reativá-lo, configure `ENABLE_RANKING=true` no ambiente e reinicie a aplicação; ele ficará disponível também em `http://127.0.0.1:8000/ranking`.

## Funcionalidades

- O Dividend Yield é recalculado com os dividendos do último ano civil completo divididos pelo preço atual, independentemente do período escolhido para o preço justo. Divergências em relação à fonte e distribuições anuais atípicas são sinalizadas.
- Na interface, o preço justo usa os últimos 3 ou 5 anos civis encerrados (padrão: 3) ou todos os anos retornados até a consulta. A API também aceita os pagamentos dos últimos 12 meses (LTM). Os períodos de 3 e 5 anos contabilizam anos sem registros como zero e os sinalizam; todo o histórico inclui apenas anos retornados, inclusive o ano atual parcial, sem pagamentos futuros. Ano encerrado não garante que a fonte contenha todos os registros.
- O LTM soma pagamentos com data entre a data equivalente do ano anterior (exclusiva) e a data da consulta (inclusiva). Registros sem data de pagamento válida ou com apenas prazo são omitidos, com aviso de que o total pode estar incompleto. Se não houver datas de pagamento, o indicador fica indisponível e a análise LTM é recusada. O Yahoo Finance fornece datas ex-dividendo, não datas de pagamento; seus anos são agregados por data ex e não permitem LTM pago. Quando a BRAPI não informa a data de pagamento de um registro, seu ano pode ser baseado na data ex ou data-com, com aviso.
- O campo de taxa é editável; 6%, 8% e 10% são sugestões, não recomendações. A classificação considera 10% e -10% como Justa, 30% como Barata e -30% como Cara.
- O resumo mostra mínimo, máximo e média anual dos valores utilizados. O crescimento médio é a média aritmética das variações percentuais anuais consecutivas; fica indisponível em caso de lacunas, anos sem registro ou base zero. No LTM, estatísticas de anos civis não se aplicam. Os cenários de 6%, 8% e 10% usam os mesmos dividendos selecionados.
- A contagem de eventos representa registros válidos retornados pela fonte, inclusive eventuais pagamentos futuros, e pode diferir da quantidade usada no cálculo.
- A análise apresenta a fonte e a data da consulta, os dividendos anuais usados, a memória completa do cálculo e gráficos de preço e dividendos.
- Valores financeiros e percentuais são exibidos com duas casas decimais; os cálculos usam a precisão original, portanto os resultados podem diferir de operações feitas com os valores arredondados mostrados na tela.
- Quando ativado, o ranking consulta BBAS3, BBSE3, ITSA4, PETR4, TAEE11, CMIG4, TRPL4 e SAPR4. Alterar a ordenação reutiliza os dados carregados, sem novas consultas; use "Atualizar ranking" para consultar novamente. A comparação aceita até quatro ativos.
- Ao consultar um ticker com pares setoriais cadastrados, a comparação é preenchida e executada automaticamente. Os grupos de pares são uma lista curada em `app/services/sector_peer_service.py`; quando um provedor não retorna dados para um par, os demais ativos disponíveis continuam sendo exibidos. A comparação automática continua gerando consultas, mesmo com o ranking desativado.
- Clique no ticker de uma coluna da comparação para calcular e carregar sua análise, mantendo a taxa e o período selecionados. Quando o ranking estiver ativado, atualize-o após alterar esses parâmetros.
- O campo de ativo pesquisa localmente por ticker, símbolo Yahoo ou nome, inclusive sem acentos, e apresenta até 10 sugestões selecionáveis por mouse ou teclado. O catálogo `data/ativos_b3.json` é carregado uma vez por página; trata-se de um snapshot sem atualização automática ou garantia de cobertura completa. A consulta do ativo selecionado ainda depende das fontes de mercado.
- A página `/cash-yield` lista as 30 melhores ações para compra pelo critério de cash-yield: y1 = dividendos do ano ÷ preço atual × 100 igual ou superior a 6 em cada um dos três últimos anos civis encerrados, com dividendos pagos em todos eles. A ordenação usa o menor y1 dos três anos e, em empate, o y1 do último ano. A página `/gerarlista` inicia ou atualiza a varredura em segundo plano (pode levar vários minutos) no catálogo completo ou, pelo botão **Gerar piloto**, apenas nos 4 ativos de validação (`ITUB4, BBAS3, WEGE3, VALE3`, configuráveis por `MARKET_TICKERS`); a varredura do piloto substitui temporariamente a lista exibida e inclui um aviso no resultado. O resultado é salvo em `data/cash_yield_cache.json` (configurável por `CASH_YIELD_CACHE_PATH`; `CASH_YIELD_WORKERS` define as consultas simultâneas, padrão 4). O universo são as ações e units de `data/ativos_b3.json`. Os dados de cada ativo ficam salvos no SQLite da aplicação (`DATABASE_PATH`): os dividendos são reutilizados por 30 dias (ou até a virada do ano) e o preço por 1 dia; só o que estiver vencido é consultado novamente, e ativos não encontrados são lembrados por 1 dia. Em ambientes com disco temporário (como o Cloud Run), defina `STORAGE_BACKEND=firestore` para guardar os dados dos ativos, a lista pronta e o progresso da varredura no Firestore, que persistem entre deploys e instâncias (opcionais: `FIRESTORE_PROJECT` e `FIRESTORE_PREFIX`; passo a passo em `docs/configuracao-firestore.md`). É preciso ativar o Firestore no projeto Google (modo Native) e conceder à conta de serviço do Cloud Run o papel "Cloud Datastore User". Sem essa variável, o padrão continua sendo o SQLite local. O y1 histórico usa o preço atual, pois as fontes não informam o preço da época de cada pagamento, e tarifas reguladas, notícias, empresas do mesmo grupo e a conversão em dólar exigem verificação manual. Após o y1, a varredura consulta indicadores de balanço no Yahoo Finance (salvos no cache) e exclui ações com dívida líquida/EBITDA acima de 3, EBITDA ≤ 0 com dívida, caixa operacional negativo, ROE negativo ou volume médio abaixo de R$ 1 milhão/dia; dívida/EBITDA acima de 2, volume abaixo de R$ 5 milhões, FCF negativo, liquidez corrente abaixo de 1 ou dados ausentes geram "atenção". A lista ordena primeiro as aprovadas. Os limites estão em `app/services/bazin_analysis.py`.
- A interface usa tema escuro por padrão, respeita a preferência salva e oferece carregamento visual e layout responsivo.

## API

- `GET /api/v1/valuation/{ticker}?taxa=0.06&periodo=5anos` calcula um ativo.
- `GET /api/v1/ranking?ordem=potencial` consulta o ranking quando habilitado; caso contrário, retorna HTTP 503 sem consultar as fontes. `ordem` aceita `potencial`, `dy` ou `classificacao`.
- `GET /api/v1/cash-yield/{ticker}/analise?taxa=0.06` retorna a análise detalhada Bazin (veredito; preço-teto principal pela média do DPA dos 3 últimos anos fechados, comparação com o LTM e preço-teto conservador; saúde financeira adaptada ao setor — bancos e holdings não são avaliados por dívida/EBITDA — e riscos, incluindo ponto do ciclo, classes ON/PN e payout). Indicadores ausentes são informados como indisponíveis, nunca estimados.
- `GET /api/v1/cash-yield` retorna o último resultado da seleção por cash-yield (`status`: `vazio`, `calculando` ou `pronto`); `POST /api/v1/cash-yield/refresh` inicia uma nova varredura e responde HTTP 202.
- `GET /api/v1/comparison?tickers=ITSA4&tickers=BBAS3` compara de um a quatro ativos.
- `GET /api/v1/market/{ticker}?inicio=2024-01-01&fim=2024-12-31` lê o histórico de cotações e proventos persistido pelo pipeline de mercado. Aceita `incluir_cotacoes=false` e `incluir_proventos=false`; sem `fim`, usa a data corrente na B3; sem `inicio`, usa `MARKET_YEARS` anos. Responde 400 para ticker/data inválidos ou intervalo acima de `MARKET_MAX_RANGE_DAYS` e 503 quando o Firestore ou o ADC estão indisponíveis.

As taxas da API são decimais: `0.06` representa 6%. Na interface, a taxa é informada em porcentagem.
Os três endpoints aceitam `periodo=ltm`, `3anos`, `5anos` ou `todos` (padrão: `5anos`).

A BRAPI pode exigir autenticação e um plano que inclua os dados de proventos. Configure a chave na variável de ambiente `BRAPI_API_KEY` antes de iniciar o servidor; não a inclua no código ou no Git. Sem acesso à BRAPI, o fallback Yahoo Finance continua disponível, mas não permite calcular pagamentos LTM.

Para investigar falhas, consulte os logs do serviço: as mensagens da aplicação informam o ticker e, quando disponível, o status HTTP da BRAPI ou o tipo da exceção. Elas não incluem a chave, URLs de requisição nem o conteúdo das respostas. Status 401, 403 e 429 podem indicar, respectivamente, problema de autenticação, restrição do plano ou limite de requisições; consulte também a documentação da fonte. Mensagens emitidas por bibliotecas externas podem ter outro formato.

## Pipeline de mercado

O pacote `src/` ingere cotações e proventos da B3 no Firestore e é executado como
Cloud Run Job, separado da aplicação web:

```bash
python -m src.cli --full --dry-run
python -m src.cli --full
python -m src.cli --incremental
```

- Modos `--full` (janela de `MARKET_YEARS` anos) e `--incremental` (últimos
  `MARKET_INCREMENTAL_DAYS` dias). `--dry-run` não cria cliente Firestore e não
  exige ADC.
- Universo: `--catalog`/`MARKET_TICKERS_FROM_CATALOG=true` (376 ações e units),
  `--tickers-file` (`.json` ou `.txt`) ou `--tickers`/`MARKET_TICKERS` (piloto:
  `ITUB4,BBAS3,WEGE3,VALE3`).
- Escritas idempotentes com `merge=True` e ID determinístico de provento
  (`ticker_tipo_data_com_valor`); o incremental une os pregões por data e não
  apaga dias antigos.
- Autenticação apenas por ADC. Variáveis: `GOOGLE_CLOUD_PROJECT`,
  `FIRESTORE_PROJECT`, `FIRESTORE_DATABASE`, `MARKET_FIRESTORE_PREFIX`,
  `MARKET_YEARS`, `MARKET_INCREMENTAL_DAYS`, `MARKET_MAX_RANGE_DAYS`,
  `MARKET_WORKERS`, `MARKET_BATCH_SIZE`, `MARKET_MAX_RETRIES`,
  `MARKET_RETRY_BACKOFF`, `MARKET_B3_COTAHIST_DIR` e `MARKET_B3_EVENTS_URL`.
  Exemplo completo em `.env.example`.
- A fonte oficial de eventos da B3 depende de `MARKET_B3_EVENTS_URL`; sem ela,
  os proventos vêm do Yahoo Finance e a API sinaliza que `data_com` é igual à
  data ex e que `data_pagamento` está indisponível.
- Índice composto de `proventos` (`ticker`, `data_com`) em
  `firestore.indexes.json`; deploy, Jobs, agendamento e diagnóstico em
  `docs/operacao-pipeline-mercado.md`.

## Testes

```bash
python -m pytest --cov=app --cov=src --cov-report=term-missing
node --test app/tests/test_ranking_ui.js app/tests/test_asset_search.js
```

O histórico SQLite fica em `data/valuation_history.sqlite`, é criado automaticamente e não é versionado. A taxa padrão pode ser configurada pela variável `BAZIN_RATE`.
