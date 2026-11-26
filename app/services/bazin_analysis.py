import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

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


CYCLICAL_SECTORS = {"Basic Materials", "Energy", "Consumer Cyclical", "Industrials"}
HOLDING_INDUSTRIES = {"Conglomerates", "Financial Conglomerates", "Asset Management"}


def business_profile(fund: Fundamentals | None, company: str = "") -> str:
    """Classifica o modelo de negócio a partir do setor/indústria informados pela fonte: banco, holding, ciclica ou padrao."""
    if fund is None:
        return "padrao"
    industry = fund.industria or ""
    if industry.startswith(("Banks", "Credit Services", "Insurance")):
        return "banco"
    if industry in HOLDING_INDUSTRIES or "HOLDING" in company.upper():
        return "holding"
    if fund.setor in CYCLICAL_SECTORS:
        return "ciclica"
    return "padrao"


def assess_fundamentals(fund: Fundamentals | None, company: str = "") -> list[Criterio]:
    """Critérios de saúde financeira. Só endividamento, liquidez na bolsa, caixa e prejuízo podem reprovar."""
    fund = fund or Fundamentals()
    criteria: list[Criterio] = []
    profile = business_profile(fund, company)

    ratio = None
    if profile in ("banco", "holding"):
        criteria.append(Criterio(
            "Dívida líquida / EBITDA", APROVADO, "n/a",
            "Não aplicável a bancos e seguradoras: a dívida é parte da operação. Avalie ROE, inadimplência, margem financeira, eficiência e payout (não disponíveis nesta fonte)."
            if profile == "banco" else
            "Não aplicável a holdings: o EBITDA reflete apenas o caixa da própria holding. Avalie desconto de holding, caixa/dívida da holding e dependência do ativo principal (não disponíveis nesta fonte).",
        ))
    elif fund.divida_liquida is None or fund.ebitda is None:
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

    if profile == "banco":
        criteria.append(Criterio("Geração de caixa", APROVADO, "n/a", "O fluxo de caixa operacional de instituições financeiras não é comparável ao de empresas comuns."))
    elif fund.fluxo_caixa_operacional is None:
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


CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "ativos_b3.json"
CLASS_LABELS = {"3": "ON", "4": "PN", "5": "PNA", "6": "PNB", "11": "UNIT"}
PROFILE_LABELS = {"banco": "banco/seguradora", "holding": "holding", "ciclica": "setor cíclico", "padrao": "empresa comum"}


@lru_cache(maxsize=1)
def _catalog_tickers() -> frozenset[str]:
    try:
        return frozenset(item["ticker"] for item in json.loads(CATALOG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()


def sibling_classes(ticker: str) -> list[str]:
    """Outras classes da mesma empresa listadas na B3 (ON/PN/UNIT), pelo prefixo de 4 letras do ticker."""
    match = re.fullmatch(r"([A-Z]{4})(\d{1,2})", ticker.upper())
    if not match:
        return []
    base, own = match.groups()
    return sorted(
        f"{base}{suffix} ({label})" for suffix, label in CLASS_LABELS.items()
        if suffix != own and f"{base}{suffix}" in _catalog_tickers()
    )


def assess_payout(fund: Fundamentals | None) -> Criterio:
    payout = fund.payout if fund else None
    if payout is None:
        return Criterio("Payout", ATENCAO, None, UNAVAILABLE)
    if payout > 100:
        return Criterio("Payout", ATENCAO, f"{_number(payout)}%", "Distribui mais que o lucro: o nível de proventos pode ser insustentável.")
    return Criterio("Payout", APROVADO, f"{_number(payout)}%", "Distribuição dentro do lucro (indicador de contexto; não inclui recompras).")


def analyze(asset, taxa: float, ltm, average):
    """Monta a análise detalhada: veredito, preço-teto (3 anos fechados e LTM), saúde financeira e riscos.

    `average` deve ser o cálculo da média dos 3 últimos anos fechados.
    """
    from app.schemas.cash_yield import AnaliseResponse, CriterioResponse, DpaAnoResponse, PrecoTetoResponse

    today = date.today()
    price = asset.preco_atual
    dpa_ltm = ltm.dividendos_ltm if ltm is not None else None
    dpa_3 = average.dividendos_medios
    teto_ltm = dpa_ltm / taxa if dpa_ltm is not None else None
    teto_3 = dpa_3 / taxa
    conservative_dpa = min(value for value in (dpa_ltm, dpa_3) if value is not None)
    conservative = conservative_dpa / taxa
    years = [DpaAnoResponse(ano=year, dpa=_round(value)) for year, value in sorted(average.dividendos_historicos.items())]
    profile = business_profile(asset.fundamentos, asset.empresa)
    sibling = sibling_classes(asset.ticker)

    notes = [
        f"Preço-teto principal = DPA médio dos 3 últimos anos fechados ({years[0].ano}–{years[-1].ano}) ÷ rendimento mínimo. O LTM e o cenário conservador servem de comparação.",
        "O LTM soma os pagamentos pela data de pagamento, evitando contar o mesmo provento na declaração e no pagamento.",
        "As fontes não separam JCP de dividendos nem identificam proventos extraordinários: os valores são brutos e a tributação do JCP pode diferir.",
        "O cenário conservador usa o menor DPA entre a média de 3 anos e o LTM.",
    ]
    if ltm is None:
        notes.append("O LTM não está disponível nesta fonte (sem datas de pagamento); o cenário conservador usa apenas a média de 3 anos.")
    notes.extend(average.avisos)

    dy = conservative_dpa / price * 100
    floor_ok = dy >= taxa * 100
    principals = [Criterio(
        "Piso de Dividend Yield", APROVADO if floor_ok else REPROVADO, f"{_number(dy)}%",
        f"Dividend Yield conservador (menor entre média de 3 anos e LTM) {'igual ou acima' if floor_ok else 'abaixo'} do mínimo de {_number(taxa * 100)}%.",
    )]
    health = assess_fundamentals(asset.fundamentos, asset.empresa)
    result = verdict(principals + health[:4])
    all_health = health + [assess_payout(asset.fundamentos)]

    risks = dividend_alerts(asset.dividendos_historicos, today)
    if dpa_ltm is not None and dpa_3 > 0:
        if dpa_ltm < dpa_3 * 0.7:
            risks.append("O DPA dos últimos 12 meses está mais de 30% abaixo da média de 3 anos: possível queda estrutural dos proventos, retenção de caixa/CAPEX ou redução de payout (value trap).")
        elif dpa_ltm > dpa_3 * 1.3:
            risks.append("O DPA dos últimos 12 meses está mais de 30% acima da média de 3 anos: pode incluir proventos extraordinários; a média de 3 anos é a referência mais prudente.")
    closed = {year: asset.dividendos_historicos.get(year, 0.0) for year in range(today.year - 5, today.year)}
    older = [closed[year] for year in range(today.year - 5, today.year - 3)]
    if older and sum(older) > 0 and dpa_3 > (sum(older) / len(older)) * 1.3:
        risks.append("A média dos 3 últimos anos está mais de 30% acima dos 2 anos anteriores: a janela pode estar em um pico de ciclo ou de payout.")
    if profile == "ciclica":
        risks.append("Setor cíclico (commodities, varejo, indústria): confirme em que ponto do ciclo a janela de 3 anos se encontra e evite extrapolar picos.")
    if profile == "banco":
        risks.append("Banco/seguradora: avalie também inadimplência, margem financeira, eficiência e histórico de payout (indisponíveis nesta fonte).")
    if profile == "holding":
        risks.append("Holding: avalie o desconto de holding, o caixa e a dívida da própria holding, pautas jurídicas/societárias e a dependência do ativo principal (indisponíveis nesta fonte).")
    if price > teto_3:
        risks.append("O preço atual está acima do preço-teto da média de 3 anos.")
    if sibling:
        risks.append(f"A empresa também negocia como {', '.join(sibling)}: compare liquidez e proventos entre as classes (ON vs. PN); esses dados não foram consultados.")
    risks.extend(f"{item.nome}: {item.texto}" for item in all_health if item.status != APROVADO and item.texto != UNAVAILABLE)
    risks.append("Notícias, fatos relevantes, processos e crises operacionais não são verificados automaticamente.")

    label = {"aprovada": "aprovada", "atencao": "com pontos de atenção", "reprovada": "reprovada"}[result]
    unavailable = sum(item.texto == UNAVAILABLE for item in all_health)
    summary = (
        f"{asset.ticker} ({PROFILE_LABELS[profile]}{'' if asset.fundamentos and (asset.fundamentos.setor or asset.fundamentos.industria) else ', classificação indisponível'}) "
        f"está {label} nos critérios principais de Bazin. Preço atual {_money_cents(price)}; "
        f"preço-teto principal (3 anos) {_money_cents(teto_3)}; conservador {_money_cents(conservative)}."
    )
    if unavailable:
        summary += f" {unavailable} indicador(es) indisponível(is) na fonte."
    return AnaliseResponse(
        ticker=asset.ticker, empresa=asset.empresa, veredito=result, resumo=summary, preco_atual=round(price, 8),
        perfil=PROFILE_LABELS[profile],
        preco_teto=PrecoTetoResponse(
            taxa=taxa, dpa_anos=years, dpa_media_3anos=_round(dpa_3), preco_teto_3anos=_round(teto_3),
            margem_3anos=_round((teto_3 / price - 1) * 100),
            dpa_ltm=_round(dpa_ltm), preco_teto_ltm=_round(teto_ltm),
            margem_ltm=_round((teto_ltm / price - 1) * 100) if teto_ltm is not None else None,
            preco_teto_conservador=_round(conservative), margem_conservador=_round((conservative / price - 1) * 100),
            observacoes=list(dict.fromkeys(notes)),
        ),
        criterios_principais=[CriterioResponse(**vars(item)) for item in principals + health[:4]],
        saude_financeira=[CriterioResponse(**vars(item)) for item in all_health],
        riscos=list(dict.fromkeys(risks)),
    )


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _money_cents(value: float) -> str:
    return f"R$ {value:.2f}".replace(".", ",")
