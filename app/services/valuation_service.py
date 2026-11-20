from datetime import datetime, timezone
from math import isfinite
from statistics import median

from app.core.config import settings
from app.models.valuation import AssetData, DividendPeriod, Valuation


class ValuationService:
    def calculate(
        self, asset: AssetData, rate: float | None = None, period: DividendPeriod = "5anos"
    ) -> Valuation:
        taxa = settings.bazin_rate if rate is None else rate
        if not isfinite(taxa) or not 0 < taxa <= 1:
            raise ValueError("A taxa Bazin deve estar entre 0 e 1.")
        if not isfinite(asset.preco_atual) or asset.preco_atual <= 0:
            raise ValueError("O preço atual do ativo deve ser positivo.")

        if period not in ("ltm", "3anos", "5anos", "todos"):
            raise ValueError("Período de dividendos inválido.")
        if any(not isfinite(valor) or valor < 0 for valor in asset.dividendos_historicos.values()):
            raise ValueError("Os dividendos retornados pela API contêm valores inconsistentes.")
        if not any(asset.dividendos_historicos.values()):
            raise ValueError("Não há dividendos válidos para calcular o Método de Bazin.")

        now = datetime.now(timezone.utc)
        today = now.astimezone().date()
        try:
            cutoff = today.replace(year=today.year - 1)
        except ValueError:
            cutoff = today.replace(year=today.year - 1, day=28)
        ltm_payments = None
        dividendos_ltm = None
        if asset.pagamentos is not None:
            if any(not isfinite(item.valor) or item.valor < 0 for item in asset.pagamentos):
                raise ValueError("Os dividendos retornados pela API contêm valores inconsistentes.")
            ltm_payments = tuple(sorted(
                (item for item in asset.pagamentos if cutoff < item.data <= today),
                key=lambda item: item.data,
            ))
            dividendos_ltm = sum(item.valor for item in ltm_payments)

        complete_history = {
            year: value for year, value in asset.dividendos_historicos.items() if year < today.year
        }
        if period == "ltm":
            if dividendos_ltm is None or ltm_payments is None:
                raise ValueError("Os dividendos pagos nos últimos 12 meses não estão disponíveis nesta fonte.")
            historico: dict[int, float] = {}
            for item in ltm_payments:
                historico[item.data.year] = historico.get(item.data.year, 0.0) + item.valor
            dividendos_medios = dividendos_ltm
        else:
            if period == "todos":
                historico = dict(sorted(
                    (year, value) for year, value in asset.dividendos_historicos.items()
                    if year <= today.year
                ))
                if not historico:
                    raise ValueError("Não há histórico de dividendos disponível para cálculo.")
            else:
                first_year = today.year - (3 if period == "3anos" else 5)
                historico = {
                    year: complete_history.get(year, 0.0)
                    for year in range(first_year, today.year)
                }
                if not any(year in complete_history for year in historico):
                    raise ValueError("Não há registros de dividendos nos anos selecionados.")
            dividendos_medios = sum(historico.values()) / len(historico)
        valores = list(historico.values())
        preco_justo = dividendos_medios / taxa
        margem = ((preco_justo - asset.preco_atual) / asset.preco_atual) * 100

        classification_margin = round(margem, 8)
        if classification_margin > 30:
            status = "Muito Barata"
        elif classification_margin > 10:
            status = "Barata"
        elif classification_margin >= -10:
            status = "Justa"
        elif classification_margin >= -30:
            status = "Cara"
        else:
            status = "Muito Cara"

        avisos = list(asset.avisos)
        if period == "todos" and today.year in historico:
            avisos.append(
                f"Os dividendos de {today.year} podem estar incompletos na fonte de dados "
                "e poderão sofrer alterações até o encerramento do ano."
            )
        anos_sem_dividendos = [str(ano) for ano, valor in historico.items() if valor == 0]
        if anos_sem_dividendos:
            avisos.append(
                "Sem dividendos registrados em "
                + ", ".join(anos_sem_dividendos)
                + "; confirme se os dados estão completos."
            )

        positivos = [valor for valor in valores if valor > 0]
        if len(positivos) >= 3:
            for ano, valor in historico.items():
                outros = [item for outro_ano, item in historico.items() if outro_ano != ano and item > 0]
                if len(outros) >= 2 and valor > median(outros) * 2.5:
                    avisos.append(
                        f"O dividendo de {ano} parece atípico frente aos demais anos. "
                        "Ele foi mantido na média; confirme se foi extraordinário."
                    )

        dividendos_anuais = complete_history.get(today.year - 1, 0.0)
        if today.year - 1 not in complete_history and period == "ltm":
            avisos.append("Não há registro de dividendos para o último ano completo; confirme o Dividend Yield.")
        dividend_yield = dividendos_anuais / asset.preco_atual * 100
        if dividend_yield > 20:
            avisos.append(
                "O Dividend Yield calculado supera 20%; valide se houve distribuição extraordinária."
            )
        if asset.dividend_yield is not None:
            reported_yield = asset.dividend_yield
            if not isfinite(reported_yield) or reported_yield < 0:
                avisos.append("O Dividend Yield informado pela fonte contém um valor inválido.")
            elif abs(reported_yield - dividend_yield) > max(2.0, dividend_yield * 0.30):
                avisos.append(
                    "O Dividend Yield informado pela fonte diverge dos dividendos anuais "
                    "e do preço atual; foi recalculado com esses dados."
                )

        return Valuation(
            ticker=asset.ticker,
            empresa=asset.empresa,
            preco_atual=asset.preco_atual,
            dividend_yield=dividend_yield,
            dividendos_historicos=historico,
            dividendos_medios=dividendos_medios,
            taxa_bazin=taxa,
            preco_justo=preco_justo,
            margem_seguranca=margem,
            status=status,
            fonte=asset.fonte,
            data_consulta=now,
            avisos=tuple(dict.fromkeys(avisos)),
            periodo=period,
            dividendos_ltm=dividendos_ltm,
            pagamentos_ltm=ltm_payments,
            ano_dividend_yield=today.year - 1,
            dividendos_dividend_yield=dividendos_anuais,
            eventos_encontrados=asset.eventos_encontrados,
            anos_registrados=frozenset(asset.dividendos_historicos),
        )
