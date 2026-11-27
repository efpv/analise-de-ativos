"""Fakes de Firestore para testes sem rede, ADC ou emulador."""

from __future__ import annotations


class FakeSnapshot:
    def __init__(self, document_id: str, data: dict | None, exists: bool = True) -> None:
        self.id = document_id
        self._data = data
        self.exists = exists

    def to_dict(self) -> dict | None:
        return dict(self._data) if self._data is not None else None


class FakeDocumentReference:
    def __init__(self, client: "FakeFirestoreClient", path: str) -> None:
        self._client = client
        self.path = path

    @property
    def id(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    def collection(self, name: str) -> "FakeCollection":
        return FakeCollection(self._client, f"{self.path}/{name}")

    def get(self) -> FakeSnapshot:
        data = self._client.data.get(self.path)
        return FakeSnapshot(self.id, data, exists=data is not None)

    def set(self, data: dict, merge: bool = True) -> None:
        current = self._client.data.get(self.path)
        if merge and current:
            current.update(data)
        else:
            self._client.data[self.path] = dict(data)
        self._client.write_count += 1


def _matches(data: dict, filter_) -> bool:
    value = data.get(filter_.field_path)
    op = filter_.op_string
    if op == "==":
        return value == filter_.value
    if op == ">=":
        return value is not None and value >= filter_.value
    raise AssertionError(f"Operador não suportado no fake: {op}")


class FakeQuery:
    def __init__(self, client: "FakeFirestoreClient", path: str) -> None:
        self._client = client
        self._path = path
        self._filters = []
        self._order = None

    def where(self, filter=None, **kwargs) -> "FakeQuery":
        if filter is None:
            raise AssertionError("O fake exige filter=FieldFilter(...).")
        self._filters.append(filter)
        return self

    def order_by(self, field: str) -> "FakeQuery":
        self._order = field
        return self

    def stream(self) -> list[FakeSnapshot]:
        snapshots = self._client.direct_documents(self._path)
        for filter_ in self._filters:
            snapshots = [
                snapshot
                for snapshot in snapshots
                if _matches(snapshot.to_dict() or {}, filter_)
            ]
        if self._order:
            snapshots.sort(
                key=lambda snapshot: (snapshot.to_dict() or {}).get(self._order, "")
            )
        return snapshots


class FakeCollection:
    def __init__(self, client: "FakeFirestoreClient", path: str) -> None:
        self._client = client
        self.path = path
        self.fail_on_query = False

    def document(self, document_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self._client, f"{self.path}/{document_id}")

    def where(self, filter=None, **kwargs) -> FakeQuery:
        if self.fail_on_query or self.path in self._client.fail_query_paths:
            from google.api_core.exceptions import FailedPrecondition

            raise FailedPrecondition("índice ausente")
        return FakeQuery(self._client, self.path).where(filter=filter)

    def order_by(self, field: str) -> FakeQuery:
        return FakeQuery(self._client, self.path).order_by(field)

    def stream(self) -> list[FakeSnapshot]:
        return self._client.direct_documents(self.path)


class FakeBatch:
    def __init__(self, client: "FakeFirestoreClient") -> None:
        self._client = client
        self._ops: list[tuple[str, dict]] = []
        self.failures: list[Exception | None] = []

    def set(self, reference: FakeDocumentReference, data: dict, merge: bool = True) -> None:
        self._ops.append((reference.path, dict(data)))

    def commit(self) -> None:
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        for path, data in self._ops:
            current = self._client.data.get(path)
            if current:
                current.update(data)
            else:
                self._client.data[path] = dict(data)
            self._client.write_count += 1
        self._ops.clear()
        self._client.commit_count += 1


class FakeFirestoreClient:
    def __init__(self, data: dict | None = None) -> None:
        self.data: dict[str, dict] = data or {}
        self.write_count = 0
        self.commit_count = 0
        self.batches: list[FakeBatch] = []
        self.fail_query_paths: set[str] = set()

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, name)

    def batch(self) -> FakeBatch:
        batch = FakeBatch(self)
        self.batches.append(batch)
        return batch

    def direct_documents(self, path: str) -> list[FakeSnapshot]:
        prefix = f"{path}/"
        snapshots = []
        for key, value in self.data.items():
            if not key.startswith(prefix):
                continue
            remainder = key[len(prefix):]
            if "/" in remainder:
                continue
            snapshots.append(FakeSnapshot(remainder, value))
        return snapshots
