"""Retry com backoff exponencial e jitter.

``attempts`` inclui a primeira tentativa: ``attempts=3`` = 1 execução + 2
retries.
"""

import logging
import random
import time
from collections.abc import Callable, Mapping
from typing import TypeVar

T = TypeVar("T")


def retry(
    func: Callable[[], T],
    *,
    attempts: int,
    base_delay: float,
    retryable: tuple[type[Exception], ...],
    logger: logging.Logger | None = None,
    context: Mapping[str, object] | None = None,
) -> T:
    """Executa ``func`` repetindo apenas exceções transitórias."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except retryable as exc:
            if attempt >= attempts:
                raise
            if logger is not None:
                logger.warning(
                    "retry",
                    extra={
                        "tentativa": attempt,
                        "tipo_erro": type(exc).__name__,
                        **(dict(context) if context else {}),
                    },
                )
            delay = base_delay * 2 ** (attempt - 1) * random.uniform(0.8, 1.2)
            time.sleep(delay)
