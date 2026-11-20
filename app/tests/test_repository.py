from app.repositories.valuation_repository import ValuationRepository


def test_repository_persists_and_lists_consultations(tmp_path):
    database = tmp_path / "history.sqlite"
    repository = ValuationRepository(str(database))
    repository.add("BBAS3", 25.0, 50.0)

    rows = repository.recent()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "BBAS3"
    assert rows[0]["preco_atual"] == 25.0
    assert rows[0]["preco_justo"] == 50.0
