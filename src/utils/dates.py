"""Janelas de datas do pipeline, alinhadas ao fuso da B3.

O Brasil não observa horário de verão desde 2019, então um offset fixo de
UTC-03:00 dispensa ``tzdata`` (que não existe por padrão no Windows).
"""

from datetime import date, datetime, timedelta, timezone

B3_TZ = timezone(timedelta(hours=-3))


def today_b3() -> date:
    """Data corrente no fuso da B3."""
    return datetime.now(B3_TZ).date()


def full_window(today: date, years: int) -> tuple[date, date]:
    """Janela de ``years`` anos encerrada em ``today``.

    Em 29/02, o ano destino pode não ser bissexto; nesse caso usa 28/02.
    """
    try:
        start = today.replace(year=today.year - years)
    except ValueError:
        start = today.replace(year=today.year - years, day=28)
    return start, today


def incremental_window(today: date, days: int) -> tuple[date, date]:
    """Janela dos últimos ``days`` dias encerrada em ``today``."""
    return today - timedelta(days=days), today
