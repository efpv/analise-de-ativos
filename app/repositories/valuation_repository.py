from collections.abc import Generator
from contextlib import contextmanager
import sqlite3
from pathlib import Path

from app.core.config import settings


class ValuationRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self.database_path = database_path or settings.database_path
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consultations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    data_consulta TEXT NOT NULL,
                    preco_atual REAL NOT NULL,
                    preco_justo REAL NOT NULL
                )
                """
            )

    def add(self, ticker: str, preco_atual: float, preco_justo: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO consultations (ticker, data_consulta, preco_atual, preco_justo) VALUES (?, date('now'), ?, ?)",
                (ticker.upper(), preco_atual, preco_justo),
            )

    def recent(self, limit: int = 10) -> list[dict]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT ticker, data_consulta, preco_atual, preco_justo FROM consultations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
