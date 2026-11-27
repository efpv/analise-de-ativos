from types import SimpleNamespace

from src import cli
from src.config import ConfigurationError, load_settings
from src.pipelines.market_pipeline import TickerResult


def _result(ticker="ITUB4", erros=()):
    return TickerResult(
        ticker=ticker, cotacoes=1, proventos=1, erros=erros, duracao_ms=1
    )


def test_cli_sucesso_exit_0(monkeypatch):
    settings = SimpleNamespace(tickers=("ITUB4",))
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: settings)
    monkeypatch.setattr(cli, "run", lambda **kwargs: (_result(),))
    assert cli.main(["--full"]) == 0


def test_cli_com_erro_exit_1(monkeypatch):
    settings = SimpleNamespace(tickers=("ITUB4",))
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: settings)
    monkeypatch.setattr(cli, "run", lambda **kwargs: (_result(erros=("falha",)),))
    assert cli.main(["--incremental"]) == 1


def test_cli_configuracao_invalida_exit_2(monkeypatch):
    def explode(**kwargs):
        raise ConfigurationError("ruim")

    monkeypatch.setattr(cli, "load_settings", explode)
    assert cli.main(["--full"]) == 2


def test_cli_dry_run_repassa_flag_e_nao_resolve_adc(monkeypatch):
    settings = SimpleNamespace(tickers=("ITUB4",))
    captured = {}

    def fake_load(**kwargs):
        captured["load"] = kwargs
        return settings

    def fake_run(**kwargs):
        captured["run"] = kwargs
        return ()

    monkeypatch.setattr(cli, "load_settings", fake_load)
    monkeypatch.setattr(cli, "run", fake_run)

    assert cli.main(["--full", "--dry-run"]) == 0
    assert captured["run"]["dry_run"] is True
    assert captured["load"]["resolve_adc_project"] is False


def test_cli_catalog_usa_376(monkeypatch):
    captured = {}

    def fake_load(*, env=None, resolve_adc_project=True):
        return load_settings(env=env, resolve_adc_project=False)

    def fake_run(**kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr(cli, "load_settings", fake_load)
    monkeypatch.setattr(cli, "run", fake_run)

    assert cli.main(["--full", "--catalog", "--dry-run"]) == 0
    assert len(captured["tickers"]) == 376


def test_cli_sem_modo_usa_full(monkeypatch):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: SimpleNamespace(tickers=("ITUB4",)))
    monkeypatch.setattr(cli, "run", fake_run)

    assert cli.main(["--dry-run"]) == 0
    assert captured["modo"] == "full"


def test_cli_tickers_file_vence_tickers(monkeypatch):
    captured = {}

    def fake_load(*, env=None, resolve_adc_project=True):
        captured["env"] = dict(env or {})
        return SimpleNamespace(tickers=("VALE3",))

    monkeypatch.setattr(cli, "load_settings", fake_load)
    monkeypatch.setattr(cli, "run", lambda **kwargs: ())

    assert cli.main(["--full", "--tickers", "PETR4", "--tickers-file", "lista.txt"]) == 0
    assert captured["env"]["MARKET_TICKERS_FILE"] == "lista.txt"
    assert "MARKET_TICKERS" not in captured["env"]


def test_cli_catalog_vence_tickers_e_arquivo(monkeypatch):
    captured = {}

    def fake_load(*, env=None, resolve_adc_project=True):
        captured["env"] = dict(env or {})
        return SimpleNamespace(tickers=("ITUB4",))

    monkeypatch.setattr(cli, "load_settings", fake_load)
    monkeypatch.setattr(cli, "run", lambda **kwargs: ())

    assert cli.main(
        ["--full", "--catalog", "--tickers", "PETR4", "--tickers-file", "lista.txt"]
    ) == 0
    assert captured["env"]["MARKET_TICKERS_FROM_CATALOG"] == "true"
    assert "MARKET_TICKERS" not in captured["env"]
    assert "MARKET_TICKERS_FILE" not in captured["env"]


def test_cli_sobrescreve_configuracoes(monkeypatch):
    captured = {}

    def fake_load(*, env=None, resolve_adc_project=True):
        captured["env"] = dict(env or {})
        return SimpleNamespace(tickers=("ITUB4",))

    monkeypatch.setattr(cli, "load_settings", fake_load)
    monkeypatch.setattr(cli, "run", lambda **kwargs: ())

    assert cli.main(
        [
            "--incremental",
            "--project",
            "projeto",
            "--database",
            "banco",
            "--workers",
            "3",
            "--days",
            "10",
            "--cotahist-dir",
            "/dados",
        ]
    ) == 0
    assert captured["env"]["GOOGLE_CLOUD_PROJECT"] == "projeto"
    assert captured["env"]["FIRESTORE_DATABASE"] == "banco"
    assert captured["env"]["MARKET_WORKERS"] == "3"
    assert captured["env"]["MARKET_INCREMENTAL_DAYS"] == "10"
    assert captured["env"]["MARKET_B3_COTAHIST_DIR"] == "/dados"


def test_cli_keyboard_interrupt_exit_1(monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: SimpleNamespace(tickers=("ITUB4",)))

    def interrompe(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run", interrompe)
    assert cli.main(["--full"]) == 1

