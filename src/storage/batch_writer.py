"""Escrita no Firestore em lotes de no máximo 500 operações."""

import logging

from src.utils.retry import retry

logger = logging.getLogger(__name__)

_FIRESTORE_RETRYABLE_NAMES = (
    "ServiceUnavailable",
    "DeadlineExceeded",
    "InternalServerError",
    "TooManyRequests",
    "Aborted",
)


def _firestore_retryable() -> tuple[type[Exception], ...]:
    try:
        from google.api_core import exceptions as api_exceptions
    except ImportError:  # pragma: no cover - dependência opcional em testes
        return ()
    return tuple(
        getattr(api_exceptions, name)
        for name in _FIRESTORE_RETRYABLE_NAMES
        if hasattr(api_exceptions, name)
    )


class BatchedWriter:
    """Acumula escritas e commita em lotes idempotentes (``merge=True``)."""

    def __init__(
        self,
        client,
        batch_size: int = 500,
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        self._client = client
        self._batch_size = min(500, max(1, batch_size))
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._batch = client.batch()
        self._ops = 0

    @property
    def pending(self) -> int:
        return self._ops

    def set(self, reference, data: dict, *, merge: bool = True) -> None:
        if not merge:
            raise ValueError("Toda escrita deve usar merge=True.")
        self._batch.set(reference, data, merge=True)
        self._ops += 1
        if self._ops >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        if self._ops == 0:
            return
        retry(
            self._batch.commit,
            attempts=self._max_retries,
            base_delay=self._base_delay,
            retryable=_firestore_retryable(),
            logger=logger,
            context={"operacao": "commit"},
        )
        self._batch = self._client.batch()
        self._ops = 0

    def __enter__(self) -> "BatchedWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.flush()
