import pytest

from src.config import (
    ConfigurationError, collection_name, load_settings, pilot_tickers, read_tickers_file,
)


def test_defaults_do_piloto():
    settings = load_settings(env={}, resolve_adc_project=False)
    assert settings.tickers == ("ITUB4", "BBAS3", "WEGE3", "VALE3")
    assert settings.years == 5
    assert settings.incremental_days == 60
    assert settings.batch_size == 500
    assert settings.workers == 2
    assert settings.firestore_database == "(default)"


def test_pilot_tickers_usa_default_de_quatro():
    assert pilot_tickers(env={}) == ("ITUB4", "BBAS3", "WEGE3", "VALE3")


def test_pilot_tickers_respeita_market_tickers():
    assert pilot_tickers(env={"MARKET_TICKERS": "petr4, vale3, PETR4"}) == ("PETR4", "VALE3")


def test_pilot_tickers_ignora_modo_catalogo():
    assert pilot_tickers(env={"MARKET_TICKERS_FROM_CATALOG": "true"}) == (
        "ITUB4", "BBAS3", "WEGE3", "VALE3",
    )


def test_catalogo_tem_376_tickers():
    settings = load_settings(
        env={"MARKET_TICKERS_FROM_CATALOG": "true"}, resolve_adc_project=False
    )
    assert len(settings.tickers) == 376
    assert settings.tickers == tuple(sorted(settings.tickers))


def test_catalogo_vence_tickers():
    settings = load_settings(
        env={
            "MARKET_TICKERS_FROM_CATALOG": "true",
            "MARKET_TICKERS": "PETR4",
        },
        resolve_adc_project=False,
    )
    assert len(settings.tickers) == 376
    assert "PETR4" in settings.tickers


def test_tickers_file_txt(tmp_path):
    path = tmp_path / "tickers.txt"
    path.write_text("# comentário\nitub4\n\nITUB4\nbbas3\n", encoding="utf-8")
    assert read_tickers_file(path) == ("ITUB4", "BBAS3")


def test_tickers_file_json(tmp_path):
    path = tmp_path / "tickers.json"
    path.write_text('[{"ticker": "vale3"}, "wege3", {"ticker": "VALE3"}]', encoding="utf-8")
    assert read_tickers_file(path) == ("VALE3", "WEGE3")


def test_tickers_file_vazio_gera_erro(tmp_path):
    path = tmp_path / "tickers.txt"
    path.write_text("# nada\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        read_tickers_file(path)


@pytest.mark.parametrize(
    ("env", "mensagem"),
    [
        ({"MARKET_YEARS": "0"}, "MARKET_YEARS deve ser maior que zero."),
        ({"MARKET_INCREMENTAL_DAYS": "0"}, "MARKET_INCREMENTAL_DAYS deve ser maior que zero."),
        ({"MARKET_WORKERS": "0"}, "MARKET_WORKERS deve ser pelo menos 1."),
        ({"MARKET_RETRY_BACKOFF": "0"}, "MARKET_RETRY_BACKOFF deve ser maior que zero."),
        ({"MARKET_MAX_RETRIES": "-1"}, "MARKET_MAX_RETRIES não pode ser negativo."),
    ],
)
def test_validacoes_numericas(env, mensagem):
    with pytest.raises(ConfigurationError, match=mensagem):
        load_settings(env=env, resolve_adc_project=False)


def test_batch_size_acima_de_500_e_ajustado():
    settings = load_settings(env={"MARKET_BATCH_SIZE": "999"}, resolve_adc_project=False)
    assert settings.batch_size == 500


def test_sem_tickers_gera_erro():
    with pytest.raises(ConfigurationError, match="Nenhum universo de tickers configurado."):
        load_settings(env={"MARKET_TICKERS": ""}, resolve_adc_project=False)


def test_resolve_adc_project_false_nao_chama_adc(monkeypatch):
    import google.auth

    def explode():
        raise AssertionError("ADC não deve ser chamado")

    monkeypatch.setattr(google.auth, "default", explode)
    settings = load_settings(env={}, resolve_adc_project=False)
    assert settings.google_cloud_project == ""


def test_collection_name_aplica_prefixo():
    settings = load_settings(
        env={"MARKET_FIRESTORE_PREFIX": "stg_"}, resolve_adc_project=False
    )
    assert collection_name(settings, "ativos") == "stg_ativos"
    assert collection_name(settings, "proventos") == "stg_proventos"


def test_collection_name_fallback_do_prefixo_legado():
    settings = load_settings(env={"FIRESTORE_PREFIX": "old_"}, resolve_adc_project=False)
    assert collection_name(settings, "ativos") == "old_ativos"


def test_collection_name_sem_prefixo():
    settings = load_settings(env={}, resolve_adc_project=False)
    assert collection_name(settings, "ativos") == "ativos"
    assert collection_name(settings, "proventos") == "proventos"


def test_prefixo_market_vence_prefixo_legado():
    settings = load_settings(
        env={"MARKET_FIRESTORE_PREFIX": "new_", "FIRESTORE_PREFIX": "old_"},
        resolve_adc_project=False,
    )
    assert collection_name(settings, "ativos") == "new_ativos"


def test_load_settings_usa_arquivo_de_tickers(tmp_path):
    path = tmp_path / "tickers.txt"
    path.write_text("vale3\nPETR4\nvale3\n", encoding="utf-8")
    settings = load_settings(
        env={"MARKET_TICKERS_FILE": str(path)}, resolve_adc_project=False
    )
    assert settings.tickers == ("VALE3", "PETR4")
    assert settings.tickers_file == str(path)


@pytest.mark.parametrize(
    ("env", "mensagem"),
    [
        ({"MARKET_YEARS": "abc"}, "MARKET_YEARS deve ser um número inteiro."),
        ({"MARKET_RETRY_BACKOFF": "abc"}, "MARKET_RETRY_BACKOFF deve ser um número."),
        ({"MARKET_MAX_RANGE_DAYS": "0"}, "MARKET_MAX_RANGE_DAYS deve ser maior que zero."),
        ({"MARKET_BATCH_SIZE": "0"}, "MARKET_BATCH_SIZE deve ser pelo menos 1."),
    ],
)
def test_valores_nao_numericos_ou_fora_da_faixa(env, mensagem):
    with pytest.raises(ConfigurationError, match=mensagem):
        load_settings(env=env, resolve_adc_project=False)


def test_catalogo_inexistente_gera_configuration_error():
    with pytest.raises(ConfigurationError, match="Não foi possível carregar"):
        load_settings(
            env={
                "MARKET_TICKERS_FROM_CATALOG": "true",
                "MARKET_CATALOG_PATH": "data/inexistente.json",
            },
            resolve_adc_project=False,
        )


def test_resolve_adc_project_usa_projeto_default(monkeypatch):
    import google.auth

    monkeypatch.setattr(
        google.auth, "default", lambda: ("credenciais", "projeto-adc")
    )
    settings = load_settings(env={}, resolve_adc_project=True)
    assert settings.google_cloud_project == "projeto-adc"


def test_resolve_adc_project_falha_gera_configuration_error(monkeypatch):
    import google.auth

    def explode():
        raise RuntimeError("sem credenciais")

    monkeypatch.setattr(google.auth, "default", explode)
    with pytest.raises(
        ConfigurationError,
        match="Projeto Google Cloud não configurado e ADC indisponível.",
    ):
        load_settings(env={}, resolve_adc_project=True)


def test_arquivo_de_tickers_json_invalido_gera_configuration_error(tmp_path):
    path = tmp_path / "tickers.json"
    path.write_text("{nao-e-json", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Não foi possível ler"):
        read_tickers_file(path)

