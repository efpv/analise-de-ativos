from math import inf
from datetime import date, timedelta
from dataclasses import replace

import pytest

from app.models.valuation import AssetData, DividendPayment
from app.services.valuation_service import ValuationService


def make_asset(price=25.0, dividends=None):
    return AssetData(
        ticker="BBAS3",
        empresa="Banco do Brasil",
        preco_atual=price,
        dividend_yield=7.5,
        dividendos_historicos=dividends if dividends is not None else {
            date.today().year - 5 + index: 2.0 + index * 0.5 for index in range(5)
        },
    )


def test_calcula_preco_justo_e_margem():
    result = ValuationService().calculate(make_asset())
    assert result.dividendos_medios == pytest.approx(3.0)
    assert result.preco_justo == pytest.approx(50.0)
    assert result.margem_seguranca == pytest.approx(100.0)


def test_classificacao_subavaliada():
    result = ValuationService().calculate(make_asset(price=38.0))
    assert result.status == "Muito Barata"


def test_classificacao_justa():
    result = ValuationService().calculate(make_asset(price=50.0))
    assert result.status == "Justa"


def test_classificacao_superavaliada():
    result = ValuationService().calculate(make_asset(price=61.0))
    assert result.status == "Cara"


@pytest.mark.parametrize(
    ("margin", "expected"),
    [
        (30.01, "Muito Barata"),
        (30, "Barata"),
        (10.01, "Barata"),
        (10, "Justa"),
        (9.99, "Justa"),
        (-10, "Justa"),
        (-10.01, "Cara"),
        (-30, "Cara"),
        (-30.01, "Muito Cara"),
    ],
)
def test_classificacao_nos_limites(margin, expected):
    fair_price = 50
    current_price = fair_price / (1 + margin / 100)
    assert ValuationService().calculate(make_asset(price=current_price)).status == expected


def test_dy_e_recalculado_com_dividendos_anuais_e_preco():
    result = ValuationService().calculate(make_asset(price=20))
    assert result.dividend_yield == pytest.approx(20)
    assert any("Dividend Yield informado" in warning for warning in result.avisos)


def test_alerta_dividendo_atipico_sem_excluir_da_media():
    history = {2021: 0.30, 2022: 0.51, 2023: 0.52, 2024: 0.62, 2025: 1.72}
    asset = AssetData("BBAS3", "Banco do Brasil", 13.17, None, history, fonte="BRAPI")
    result = ValuationService().calculate(asset)
    assert result.dividendos_medios == pytest.approx(0.734)
    assert any("parece atípico" in warning for warning in result.avisos)
    assert result.fonte == "BRAPI"
    assert result.data_consulta.tzinfo is not None


def test_rejeita_dividendos_negativos_ou_nao_finitos():
    for invalid in (-1, inf):
        history = {2022: 2, 2023: 2, 2024: 2, 2025: 2, 2026: invalid}
        with pytest.raises(ValueError, match="inconsistentes"):
            ValuationService().calculate(make_asset(dividends=history))


def test_rejeita_historico_sem_dividendos():
    with pytest.raises(ValueError, match="Não há dividendos"):
        ValuationService().calculate(make_asset(dividends={2022: 0, 2023: 0, 2024: 0, 2025: 0, 2026: 0}))


def test_taxa_invalida():
    with pytest.raises(ValueError, match="taxa Bazin"):
        ValuationService().calculate(make_asset(), rate=0)


def test_periodos_anuais_utilizam_anos_completos_e_lacunas():
    year = date.today().year
    history = {year - 7: 7, year - 5: 1, year - 3: 3, year - 2: 2, year - 1: 4, year: 100}
    service = ValuationService()
    asset = make_asset(dividends=history)
    three = service.calculate(asset, rate=0.1, period="3anos")
    five = service.calculate(asset, rate=0.1, period="5anos")
    all_years = service.calculate(asset, rate=0.1, period="todos")
    assert three.dividendos_historicos == {year - 3: 3, year - 2: 2, year - 1: 4}
    assert three.dividendos_medios == 3
    assert three.preco_justo == 30
    assert five.dividendos_medios == 2
    assert all_years.dividendos_historicos == history
    assert all_years.dividendos_medios == pytest.approx(117 / 6)
    assert any(f"dividendos de {year} podem estar incompletos" in warning for warning in all_years.avisos)
    assert any("Sem dividendos registrados" in warning for warning in five.avisos)


def test_ltm_usa_datas_de_pagamento_e_exclui_futuras_e_limite():
    today = date.today()
    try:
        cutoff = today.replace(year=today.year - 1)
    except ValueError:
        cutoff = today.replace(year=today.year - 1, day=28)
    asset = make_asset()
    asset = replace(asset, pagamentos=(
        DividendPayment(cutoff, 100),
        DividendPayment(cutoff + timedelta(days=1), 1),
        DividendPayment(today, 2),
        DividendPayment(today + timedelta(days=1), 100),
    ))
    result = ValuationService().calculate(asset, rate=0.1, period="ltm")
    assert result.dividendos_ltm == 3
    assert result.dividendos_medios == 3
    assert result.preco_justo == 30
    assert len(result.pagamentos_ltm) == 2
    assert result.dividend_yield == pytest.approx(16)


def test_ltm_indisponivel_nao_e_estimado_a_partir_dos_anos():
    with pytest.raises(ValueError, match="últimos 12 meses não estão disponíveis"):
        ValuationService().calculate(make_asset(), period="ltm")


def test_periodo_sem_nenhum_registro_nao_gera_valuation_zero():
    with pytest.raises(ValueError, match="Não há registros de dividendos nos anos selecionados"):
        ValuationService().calculate(make_asset(dividends={date.today().year: 1}), period="3anos")
