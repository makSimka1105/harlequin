from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from harlequin_pgfk import HarlequinPgFkConnection


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, sql: str) -> None:
        pass

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class FakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.rows)


class FakePool:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    @contextmanager
    def connection(self) -> Iterator[FakeConnection]:
        yield FakeConnection(self.rows)


def test_foreign_keys_carry_nullability() -> None:
    connection = HarlequinPgFkConnection.__new__(HarlequinPgFkConnection)
    connection.pool = FakePool(  # type: ignore[assignment]
        [
            (
                "customer_personid_fkey",
                "sales",
                "customer",
                ["personid"],
                "person",
                "person",
                ["personid"],
                "retail_training",
                True,
            )
        ]
    )

    [edge] = connection.get_foreign_keys()

    assert edge.from_relation == '"sales"."customer"'
    assert edge.to_columns == ("personid",)
    assert edge.database == "retail_training"
    assert edge.nullable is True


def test_column_details_keep_the_catalog_spelling() -> None:
    connection = HarlequinPgFkConnection.__new__(HarlequinPgFkConnection)
    connection.pool = FakePool(  # type: ignore[assignment]
        [
            (
                "sales",
                "customer",
                "personid",
                2,
                "integer",
                True,
                None,
                False,
                False,
                True,
                "who the customer is",
                "retail_training",
            )
        ]
    )

    [column] = connection.get_column_details()

    assert column.relation == '"sales"."customer"'
    assert column.name == "personid"
    assert column.position == 2
    assert column.type_name == "integer"
    assert column.nullable is True
    assert column.default is None
    assert (column.primary_key, column.unique, column.indexed) == (False, False, True)
    assert column.comment == "who the customer is"
    assert column.database == "retail_training"
