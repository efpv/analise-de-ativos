"""Leitura do catálogo local de ativos da B3."""

import json
from pathlib import Path

CATALOG_TYPES = frozenset({"STOCK", "UNIT"})
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    fallback = _REPO_ROOT / candidate
    return fallback if fallback.exists() else candidate


def catalog_tickers(path: str | Path = "data/ativos_b3.json") -> tuple[str, ...]:
    """Retorna os tickers ``STOCK``/``UNIT`` sem sufixo ``F``, únicos e ordenados.

    Hoje o snapshot local rende exatamente 376 ativos. Erros de arquivo ou JSON
    propagam; ``load_settings`` os converte em ``ConfigurationError``.
    """
    with _resolve(path).open(encoding="utf-8") as file:
        items = json.load(file)
    return tuple(sorted({
        str(item["ticker"])
        for item in items
        if item.get("type") in CATALOG_TYPES and not str(item["ticker"]).endswith("F")
    }))
