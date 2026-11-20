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
- O preço justo usa os últimos 3 ou 5 anos civis encerrados (padrão: 5), todos os anos retornados até a consulta ou os pagamentos dos últimos 12 meses (LTM). Os períodos de 3 e 5 anos contabilizam anos sem registros como zero e os sinalizam; todo o histórico inclui apenas anos retornados, inclusive o ano atual parcial, sem pagamentos futuros. Ano encerrado não garante que a fonte contenha todos os registros.
- O LTM soma pagamentos com data entre a data equivalente do ano anterior (exclusiva) e a data da consulta (inclusiva). Registros sem data de pagamento válida ou com apenas prazo são omitidos, com aviso de que o total pode estar incompleto. Se não houver datas de pagamento, o indicador fica indisponível e a análise LTM é recusada. O Yahoo Finance fornece datas ex-dividendo, não datas de pagamento; seus anos são agregados por data ex e não permitem LTM pago. Quando a BRAPI não informa a data de pagamento de um registro, seu ano pode ser baseado na data ex ou data-com, com aviso.
- O campo de taxa é editável; 6%, 8% e 10% são sugestões, não recomendações. A classificação considera 10% e -10% como Justa, 30% como Barata e -30% como Cara.
- O resumo mostra mínimo, máximo e média anual dos valores utilizados. O crescimento médio é a média aritmética das variações percentuais anuais consecutivas; fica indisponível em caso de lacunas, anos sem registro ou base zero. No LTM, estatísticas de anos civis não se aplicam. Os cenários de 6%, 8% e 10% usam os mesmos dividendos selecionados.
- A contagem de eventos representa registros válidos retornados pela fonte, inclusive eventuais pagamentos futuros, e pode diferir da quantidade usada no cálculo.
- A análise apresenta a fonte e a data da consulta, os dividendos anuais usados, a memória completa do cálculo e gráficos de preço e dividendos.
- Quando ativado, o ranking consulta BBAS3, BBSE3, ITSA4, PETR4, TAEE11, CMIG4, TRPL4 e SAPR4. A comparação aceita até quatro ativos.
- Ao consultar um ticker com pares setoriais cadastrados, a comparação é preenchida e executada automaticamente. Os grupos de pares são uma lista curada em `app/services/sector_peer_service.py`; quando um provedor não retorna dados para um par, os demais ativos disponíveis continuam sendo exibidos. A comparação automática continua gerando consultas, mesmo com o ranking desativado.
- Clique no ticker de uma coluna da comparação para calcular e carregar sua análise, mantendo a taxa e o período selecionados. Quando o ranking estiver ativado, atualize-o após alterar esses parâmetros.
- A interface oferece tema escuro, carregamento visual e layout responsivo.

## API

- `GET /api/v1/valuation/{ticker}?taxa=0.06&periodo=5anos` calcula um ativo.
- `GET /api/v1/ranking?ordem=potencial` consulta o ranking quando habilitado; caso contrário, retorna HTTP 503 sem consultar as fontes. `ordem` aceita `potencial`, `dy` ou `classificacao`.
- `GET /api/v1/comparison?tickers=ITSA4&tickers=BBAS3` compara de um a quatro ativos.

As taxas da API são decimais: `0.06` representa 6%. Na interface, a taxa é informada em porcentagem.
Os três endpoints aceitam `periodo=ltm`, `3anos`, `5anos` ou `todos` (padrão: `5anos`).

A BRAPI pode exigir autenticação e um plano que inclua os dados de proventos. Configure a chave na variável de ambiente `BRAPI_API_KEY` antes de iniciar o servidor; não a inclua no código ou no Git. Sem acesso à BRAPI, o fallback Yahoo Finance continua disponível, mas não permite calcular pagamentos LTM.

Para investigar falhas, consulte os logs do serviço: as mensagens da aplicação informam o ticker e, quando disponível, o status HTTP da BRAPI ou o tipo da exceção. Elas não incluem a chave, URLs de requisição nem o conteúdo das respostas. Status 401, 403 e 429 podem indicar, respectivamente, problema de autenticação, restrição do plano ou limite de requisições; consulte também a documentação da fonte. Mensagens emitidas por bibliotecas externas podem ter outro formato.

## Testes

```bash
python -m pytest --cov=app --cov-report=term-missing
```

O histórico SQLite fica em `data/valuation_history.sqlite`, é criado automaticamente e não é versionado. A taxa padrão pode ser configurada pela variável `BAZIN_RATE`.
