from __future__ import annotations

from harlequin.catalog import ColumnDetails
from harlequin.relations.schema import SchemaIndex

CUSTOMER = '"sales"."customer"'


def column(name: str, position: int, relation: str = CUSTOMER) -> ColumnDetails:
    return ColumnDetails(
        relation=relation,
        name=name,
        position=position,
        type_name="bigint",
        nullable=False,
        default=None,
        primary_key=False,
        unique=False,
        indexed=False,
        comment=None,
    )


INDEX = SchemaIndex(
    [column("personid", 2), column("customerid", 1), column("name", 1, '"x"."y"')]
)


def test_columns_come_in_table_order() -> None:
    assert [c.name for c in INDEX.columns_of(CUSTOMER)] == ["customerid", "personid"]


def test_an_unknown_relation_has_no_columns() -> None:
    assert INDEX.columns_of('"sales"."nope"') == []


def test_a_column_by_name() -> None:
    found = INDEX.column(CUSTOMER, "personid")
    assert found is not None and found.position == 2


def test_an_unquoted_name_ignores_case_and_a_quoted_one_does_not() -> None:
    assert INDEX.column(CUSTOMER, "PersonID") is not None
    assert INDEX.column(CUSTOMER, '"PersonID"') is None
    assert INDEX.column(CUSTOMER, '"personid"') is not None


def test_relations_and_emptiness() -> None:
    assert INDEX.relations == ['"sales"."customer"', '"x"."y"']
    assert not SchemaIndex([])
