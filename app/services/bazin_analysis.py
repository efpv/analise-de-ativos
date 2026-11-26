from datetime import date

from app.models.cash_yield import Criterio
from app.models.valuation import Fundamentals

APROVADO, ATENCAO, REPROVADO = "aprovado", "atencao", "reprovado"
MAX_DIVIDA_EBITDA = 3.0
ALERTA_DIVIDA_EBITDA = 2.0
MIN_VOLUME_DIARIO = 1_000_000.0
ALERTA_VOLUME_DIARIO = 5_000_000.0
ROE_ALTO = 25.0
UNAVAILABLE = "Indisponível na fonte consultada."


def _money(value: float) -> str:
    return f"R$ {value:,.0f}".replace(",", ".")


def _number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def assess_fundamentals(fund: Fundamentals | None) -> list[Criterio]:
    """Critérios de saúde financeira. Só endividamento, liquidez na bolsa, caixa e prejuízo podem reprovar."""
    fund = fund or Fundamentals()
    criteria: list[Criterio] = []

    ratio = None
    if fund.divida_liquida is None or fund.ebitda is None:
        criteria.append(Criterio("Dívida líquida / EBITDA", ATENCAO, None, UNAVAILABLE))
    elif fund.divida_liquida <= 0:
        criteria.append(Criterio("Dívida líquida / EBITDA", APROVADO, "Caixa líquido", "A empresa tem mais caixa que dívida."))
    elif fund.ebitda <= 0:
        criteria.append(Criterio("Dívida líquida / EBITDA", REPROVADO, None, "Há dívida líquida e o EBITDA não é positivo."))
    else:
        ratio = fund.divida_liquida / fund.ebitda
        status = REPROVADO if ratio > MAX_DIVIDA_EBITDA else ATENCAO if ratio > ALERTA_DIVIDA_EBITDA else APROVADO
        limit = f"acima do limite de {_number(MAX_DIVIDA_EBITDA)}" if status == REPROVADO else (
            f"acima de {_number(ALERTA_DIVIDA_EBITDA)}, exige comparação com o setor" if status == ATENCAO
            else f"dentro do limite de {_number(MAX_DIVIDA_EBITDA)}"
        )
        criteria.append(Criterio("Dívida líquida / EBITDA", status, f"{_number(ratio)}x", f"Endividamento {limit}."))

    if fund.volume_financeiro is None:
        criteria.append(Criterio("Liquidez na bolsa", ATENCAO, None, UNAVAILABLE))
    else:
        status = (
            REPROVADO if fund.volume_financeiro < MIN_VOLUME_DIARIO
            else ATENCAO if fund.volume_financeiro < ALERTA_VOLUME_DIARIO else APROVADO
        )
        text = {
            REPROVADO: f"Volume médio diário abaixo de {_money(MIN_VOLUME_DIARIO)}: difícil entrar e sair sem distorcer o preço.",
            ATENCAO: f"Volume médio diário abaixo de {_money(ALERTA_VOLUME_DIARIO)}: liquidez limitada.",
            APROVADO: "Volume médio diário suficiente para entrar e sair com facilidade.",
        }[status]
        criteria.append(Criterio("Liquidez na bolsa", status, f"{_money(fund.volume_financeiro)}/dia", text))

    if fund.fluxo_caixa_operacional is None:
        criteria.append(Criterio("Geração de caixa", ATENCAO, None, UNAVAILABLE))
    elif fund.fluxo_caixa_operacional <= 0:
        criteria.append(Criterio("Geração de caixa", REPROVADO, _money(fund.fluxo_caixa_operacional), "O caixa operacional não é positivo."))
    elif fund.fluxo_caixa_livre is not None and fund.fluxo_caixa_livre < 0:
        criteria.append(Criterio(
            "Geração de caixa", ATENCAO, _money(fund.fluxo_caixa_operacional),
            "O caixa operacional é positivo, mas os investimentos (CAPEX) o superam: o fluxo de caixa livre é negativo.",
        ))
    else:
        criteria.append(Criterio("Geração de caixa", APROVADO, _money(fund.fluxo_caixa_operacional), "Caixa operacional positivo."))

    if fund.roe is None:
        criteria.append(Criterio("ROE", ATENCAO, None, UNAVAILABLE))
    elif fund.roe < 0:
        criteria.append(Criterio("ROE", REPROVADO, f"{_number(fund.roe)}%", "Retorno negativo: a empresa tem prejuízo."))
    elif fund.roe > ROE_ALTO and ratio is not None and ratio > ALERTA_DIVIDA_EBITDA:
        criteria.append(Criterio("ROE", ATENCAO, f"{_number(fund.roe)}%", "ROE elevado com alta alavancagem: parte do retorno vem da dívida."))
    else:
        criteria.append(Criterio("ROE", APROVADO, f"{_number(fund.roe)}%", "Rentabilidade positiva sobre o patrimônio."))

    if fund.liquidez_corrente is None:
        criteria.append(Criterio("Liquidez corrente", ATENCAO, None, UNAVAILABLE))
    else:
        low = fund.liquidez_corrente < 1
        criteria.append(Criterio(
            "Liquidez corrente", ATENCAO if low else APROVADO, _number(fund.liquidez_corrente),
            "Ativo circulante menor que o passivo circulante: pouca folga no curto prazo." if low else "Folga de curto prazo.",
        ))

    criteria.append(
        Criterio("P/VP", APROVADO, _number(fund.p_vp), "Indicador de contexto; não substitui o critério de Bazin.")
        if fund.p_vp is not None else Criterio("P/VP", ATENCAO, None, UNAVAILABLE)
    )
    return criteria


def verdict(criteria: list[Criterio]) -> str:
    statuses = {item.status for item in criteria}
    return "reprovada" if REPROVADO in statuses else "atencao" if ATENCAO in statuses else "aprovada"


def dividend_alerts(history: dict[int, float], today: date, years: int = 3) -> list[str]:
    """Sinaliza dividendos pontuais e cortes nos últimos anos encerrados."""
    values = {year: history.get(year, 0.0) for year in range(today.year - years, today.year)}
    alerts: list[str] = []
    for year, value in values.items():
        others = [other for other_year, other in values.items() if other_year != year]
        average = sum(others) / len(others)
        if average > 0 and value > 2 * average:
            alerts.append(
                f"O dividendo de {year} é mais que o dobro da média dos demais anos: "
                "pode incluir evento extraordinário ou dividendo especial."
            )
    ordered = sorted(values.items())
    (_, previous), (last_year, last) = ordered[-2], ordered[-1]
    if previous > 0 and last < previous * 0.5:
        alerts.append(f"O dividendo de {last_year} caiu mais de 50% em relação ao ano anterior: risco de corte de proventos.")
    return alerts


def analyze(asset, taxa: float, ltm, average):
    """Monta a análise detalhada no formato: veredito, preço-teto, saúde financeira e riscos."""
    from app.schemas.cash_yield import AnaliseResponse, CriterioResponse, PrecoTetoResponse

    today = date.today()
    price = asset.preco_atual
    dpa_ltm = ltm.dividendos_ltm if ltm is not None else None
    teto_ltm = dpa_ltm / taxa if dpa_ltm is not None else None
    teto_media = average.dividendos_medios / taxa
    reference = dpa_ltm if dpa_ltm is not None else average.dividendos_medios
    conservative = min(value for value in (teto_ltm, teto_media) if value is not None)

    notes = [
        "Preço-Teto = DPA ÷ rendimento mínimo. O LTM soma pagamentos pela data de pagamento, evitando contar o mesmo provento na declaração e no pagamento.",
        "As fontes não separam JCP de dividendos: os valores são brutos e o JCP pode ter tributação diferente.",
        "O cenário conservador usa o menor entre o preço-teto do LTM e o da média dos últimos 5 anos.",
    ]
    if ltm is None:
        notes.append("O LTM não está disponível nesta fonte (sem datas de pagamento); o veredito usa a média dos últimos 5 anos.")
    notes.extend(average.avisos)

    dy = reference / price * 100
    principals = [Criterio(
        "Piso de Dividend Yield", APROVADO if dy >= taxa * 100 else REPROVADO, f"{_number(dy)}%",
        f"Dividend Yield {'igual ou acima' if dy >= taxa * 100 else 'abaixo'} do mínimo de {_number(taxa * 100)}% "
        f"({'LTM' if ltm is not None else 'média de 5 anos'}).",
    )]
    health = assess_fundamentals(asset.fundamentos)
    result = verdict(principals + health[:4])

    risks = dividend_alerts(asset.dividendos_historicos, today)
    if dpa_ltm is not None and average.dividendos_medios > 0 and dpa_ltm < average.dividendos_medios * 0.7:
        risks.append("O DPA dos últimos 12 meses está mais de 30% abaixo da média de 5 anos: possível queda estrutural dos proventos (value trap).")
    if price > teto_media:
        risks.append("O preço atual está acima do preço-teto da média histórica.")
    risks.extend(f"{item.nome}: {item.texto}" for item in health if item.status != APROVADO and item.texto != UNAVAILABLE)
    risks.append("Notícias, fatos relevantes e o contexto setorial (por exemplo tarifas reguladas) não são verificados automaticamente.")

    label = {"aprovada": "aprovada", "atencao": "com pontos de atenção", "reprovada": "reprovada"}[result]
    unavailable = sum(item.texto == UNAVAILABLE for item in health)
    summary = f"{asset.ticker} está {label} nos critérios principais de Bazin. Preço atual {_money_cents(price)}; preço-teto conservador {_money_cents(conservative)}."
    if unavailable:
        summary += f" {unavailable} indicador(es) indisponível(is) na fonte."
    return AnaliseResponse(
        ticker=asset.ticker, empresa=asset.empresa, veredito=result, resumo=summary, preco_atual=round(price, 8),
        preco_teto=PrecoTetoResponse(
            taxa=taxa, dpa_ltm=_round(dpa_ltm), preco_teto_ltm=_round(teto_ltm),
            margem_ltm=_round((teto_ltm / price - 1) * 100) if teto_ltm is not None else None,
            dpa_media_5anos=_round(average.dividendos_medios), preco_teto_media_5anos=_round(teto_media),
            margem_media_5anos=_round((teto_media / price - 1) * 100), cenario_conservador=_round(conservative),
            observacoes=list(dict.fromkeys(notes)),
        ),
        criterios_principais=[CriterioResponse(**vars(item)) for item in principals + health[:4]],
        saude_financeira=[CriterioResponse(**vars(item)) for item in health],
        riscos=list(dict.fromkeys(risks)),
    )


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _money_cents(value: float) -> str:
    return f"R$ {value:.2f}".replace(".", ",")
