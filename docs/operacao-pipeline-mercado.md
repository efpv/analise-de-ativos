# Operação do pipeline de mercado

Runbook do pipeline que ingere cotações e proventos da B3 no Firestore e do
endpoint aditivo `GET /api/v1/market/{ticker}`.

Documentos de referência: [`PRD-pipeline-mercado.md`](PRD-pipeline-mercado.md),
[`especificacao-tecnica-pipeline-mercado.md`](especificacao-tecnica-pipeline-mercado.md)
e [`SPEC-implementacao-pipeline-mercado.md`](SPEC-implementacao-pipeline-mercado.md).

## 1. Pré-requisitos

- Projeto Google Cloud com Firestore no modo Native.
- APIs habilitadas: Cloud Run, Cloud Scheduler, Firestore e Artifact Registry.
- Conta de serviço com `roles/datastore.user` e permissão de execução do Job.
  Não use `roles/owner` nem papéis de edição de IAM.
- Prefira o banco `(default)`: bancos Firestore nomeados não têm cota gratuita.
- Autenticação apenas por ADC (`google.auth.default()`); não há chave em
  arquivo, variável ou código.

## 2. Índice composto de proventos

O caminho padrão de leitura usa `ticker ASC, data_com ASC`. Crie o índice com o
nome efetivo da coleção (`proventos` ou `{MARKET_FIRESTORE_PREFIX}proventos`):

```bash
gcloud firestore indexes composite create \
  --project=<PROJETO> \
  --collection-group=proventos \
  --field-config=field-path=ticker,order=ascending \
  --field-config=field-path=data_com,order=ascending
```

Também é possível aplicar `firestore.indexes.json` com o comando de deploy de
índices do projeto. Sem o índice, o repositório cai no filtro em Python e
registra `indice_proventos_ausente`; o resultado é o mesmo, com custo maior.

## 3. Build e publicação da imagem

A mesma imagem serve o serviço HTTP e o Job: o `ENTRYPOINT` detecta argumentos
que começam com `-` e executa `python -m src.cli`; sem esses argumentos, o `CMD`
inicia o `uvicorn`. Por isso o Job pode usar `--args="--full"` ou
`--args="--incremental"` diretamente.

```bash
gcloud builds submit --tag <REGIAO>-docker.pkg.dev/<PROJETO>/<REPO>/bazin:<TAG>
```

## 4. Jobs

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

Piloto: use `MARKET_TICKERS=ITUB4,BBAS3,WEGE3,VALE3` e timeouts menores.

## 5. Carga inicial e validação

1. `--full --dry-run` com 4 tickers para conferir volumes e datas sem escrever.
2. `--full` com 4 tickers e inspeção no Console:
   - `ativos/{ticker}` com `inicio_serie`, `fim_serie`, `ultimo_provento_em`;
   - `ativos/{ticker}/cotacoes_anuais/{ano}` com `pregoes` ordenados;
   - `proventos/{evento_id}` sem duplicatas após reexecução.
3. `--full --catalog --dry-run` (376 tickers, sem escrita).
4. `--full --catalog` e reexecução para provar idempotência.
5. `curl "http://<SERVICO>/api/v1/market/ITUB4?inicio=2024-01-01&fim=2024-12-31"`.

## 6. Agendamento

- Cloud Scheduler com OIDC para a conta de serviço que executa o Job.
- `bazin-market-incremental` diário após o fechamento da B3 (horário a
  confirmar com o responsável de produto).
- `--full` só em carga inicial ou reconstrução; não agende rotineiramente.

## 7. Diagnóstico

| Sintoma | Causa provável | Ação |
|---|---|---|
| 403 no Firestore | Conta sem `roles/datastore.user` | Ajustar IAM. |
| 404 de banco | `FIRESTORE_DATABASE` inexistente | Conferir o nome do banco. |
| 429 do yfinance | Rate limit | Reduzir `MARKET_WORKERS` e repetir. |
| `indice_proventos_ausente` | Índice composto não criado | Aplicar o índice da seção 2. |
| `sem_cotacoes` | Ticker sem negociação no período | Conferir o ticker e a janela. |
| `yahoo_fallback` | B3 indisponível ou URL vazia | Avaliar `MARKET_B3_EVENTS_URL`. |

Logs são JSON em stdout e nunca incluem token, chave, URL completa ou corpo de
resposta.

## 8. Rollback

1. Pause ou apague o agendamento do Cloud Scheduler.
2. Reverta a imagem do Job e do serviço para a tag anterior.
3. Eventos e anos antigos não são apagados pela v1; não é necessário limpar o
   Firestore para reverter a aplicação.
