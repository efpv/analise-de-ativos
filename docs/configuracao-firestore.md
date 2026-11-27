# Configuração do Firestore no Cloud Run

Passos para que a lista de cash-yield, os dados dos ativos e o progresso da varredura persistam entre deploys, reinícios e instâncias.

Substitua os valores entre `<...>`:

- `<PROJETO>`: ID do projeto Google Cloud.
- `<SERVICO>`: nome do serviço no Cloud Run.
- `<REGIAO>`: região do serviço, por exemplo `southamerica-east1`.

Os comandos `gcloud` podem ser executados no Cloud Shell ou em um terminal com o Google Cloud SDK. Todos os passos também podem ser feitos pelo Console.

## Antes de começar

O código com suporte ao Firestore está na branch `develop`. Se o Google publica a partir da `main`, faça o merge da `develop` na `main` antes ou depois da configuração. Enquanto `STORAGE_BACKEND` não estiver definida, a aplicação continua usando SQLite local, sem mudança de comportamento. Por isso a ordem não quebra nada.

## 1. Ativar a API do Firestore

```bash
gcloud services enable firestore.googleapis.com --project=<PROJETO>
```

## 2. Criar o banco de dados Firestore

O banco deve ser criado em modo **Native** (não Datastore). A região **não pode ser alterada depois**; escolha a mesma do Cloud Run ou a mais próxima.

```bash
gcloud firestore databases create --location=<REGIAO> --type=firestore-native --project=<PROJETO>
```

Se já existir um banco `(default)` no projeto, pule este passo, mas confirme que ele está em modo Native.

## 3. Descobrir a conta de serviço do Cloud Run

```bash
gcloud run services describe <SERVICO> --region=<REGIAO> --project=<PROJETO> \
  --format='value(spec.template.spec.serviceAccountName)'
```

Se o resultado vier vazio, o serviço usa a conta padrão do Compute Engine: `<NUMERO_DO_PROJETO>-compute@developer.gserviceaccount.com`. O número do projeto aparece com:

```bash
gcloud projects describe <PROJETO> --format='value(projectNumber)'
```

## 4. Dar permissão à conta de serviço

```bash
gcloud projects add-iam-policy-binding <PROJETO> \
  --member="serviceAccount:<CONTA_DE_SERVICO>" \
  --role="roles/datastore.user"
```

O papel `roles/datastore.user` ("Cloud Datastore User") dá acesso de leitura e escrita ao Firestore. Não conceda papéis mais amplos.

## 5. Definir as variáveis de ambiente do serviço

```bash
gcloud run services update <SERVICO> --region=<REGIAO> --project=<PROJETO> \
  --update-env-vars=STORAGE_BACKEND=firestore
```

Variáveis opcionais:

| Variável | Para que serve | Padrão |
| --- | --- | --- |
| `FIRESTORE_PROJECT` | Projeto do Firestore, caso seja diferente do projeto do serviço | projeto do serviço |
| `FIRESTORE_PREFIX` | Prefixo dos nomes das coleções, útil para separar ambientes (por exemplo `dev_`) | vazio |
| `CASH_YIELD_WORKERS` | Consultas simultâneas às fontes durante a varredura | `4` |
| `BRAPI_API_KEY` | Chave da BRAPI | vazio |

Alterar variáveis cria uma nova revisão do serviço, o que equivale a um deploy.

## 6. Manter a CPU alocada durante a varredura

A varredura roda em segundo plano, depois que a requisição que a iniciou já respondeu. No Cloud Run, a CPU pode ser reduzida quando não há requisições em andamento, e a varredura pode ficar lenta ou parar.

```bash
gcloud run services update <SERVICO> --region=<REGIAO> --project=<PROJETO> \
  --no-cpu-throttling
```

Esta opção aumenta o custo, porque a CPU passa a ser cobrada enquanto a instância está ativa. Se preferir não usá-la, mantenha uma instância mínima (`--min-instances=1`) e acompanhe o progresso: se a varredura travar, ela é considerada abandonada após 10 minutos e pode ser reiniciada pelo botão "Atualizar lista".

## 7. Verificar

1. Abra `/gerarlista` e clique em **Gerar lista** (catálogo com 376 ativos) ou em **Gerar piloto** (4 ativos de validação, útil para um teste rápido).
2. Confirme que o progresso ("Analisando ativos: N de 376..." ou "N de 4..." no piloto) avança.
3. No Console, em **Firestore > Dados**, confirme as coleções `asset_cache` e `cash_yield` (com os documentos `snapshot` e `progress`). Se usar `FIRESTORE_PREFIX`, os nomes começam com o prefixo.
4. Depois que a lista estiver pronta, faça um novo deploy ou reinicie o serviço e abra `/cash-yield` de novo. A lista deve continuar lá.
5. Uma nova varredura deve ser bem mais rápida: dividendos são reaproveitados por 30 dias e preços por 1 dia.

## Problemas comuns

- **`403 Missing or insufficient permissions` ou `PermissionDenied` nos logs:** a conta de serviço não tem o papel do passo 4, ou o papel foi dado a outra conta.
- **`The database (default) does not exist` / `NotFound`:** o banco não foi criado (passo 2) ou está em outro projeto (ajuste `FIRESTORE_PROJECT`).
- **Banco criado em modo Datastore:** o código usa o modo Native. Será preciso criar o banco em outro projeto, porque o modo não pode ser alterado.
- **A lista continua sumindo:** confira se `STORAGE_BACKEND=firestore` está na revisão que está recebendo tráfego.
- **Para voltar ao SQLite:** remova a variável com `gcloud run services update <SERVICO> --region=<REGIAO> --remove-env-vars=STORAGE_BACKEND`.

## Observações

- O histórico de "Consultas recentes" da página inicial continua em SQLite e é perdido quando a instância é reiniciada. Isso não afeta a seleção de cash-yield.
- O Firestore tem cota gratuita diária de leituras e escritas. Uma varredura completa faz algumas centenas de operações, bem abaixo dela. Confira a cota atual na documentação do Google Cloud.
