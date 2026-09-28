from __future__ import annotations

import pytest

from harlequin.relations.pointer import Pointer, pointer_at

SQL = "select c.personid, storeid from sales.customer c where c.customerid = 1"


def at(sql: str, word: str, shift: int = 0) -> Pointer | None:
    return pointer_at(sql, sql.index(word) + shift)


def test_a_qualified_column() -> None:
    assert at(SQL, "personid") == Pointer(qualifier="c", name="personid")


def test_the_end_of_a_word_still_points_at_it() -> None:
    assert at(SQL, "personid", len("personid")) == Pointer("c", "personid")


def test_a_bare_column() -> None:
    assert at(SQL, "storeid") == Pointer(qualifier=None, name="storeid")


def test_the_qualifier_points_at_the_table() -> None:
    assert at(SQL, "c.personid") == Pointer(qualifier=None, name="c", table=True)


def test_a_relation_in_from() -> None:
    assert at(SQL, "customer") == Pointer(None, "sales.customer", table=True)


def test_an_alias_in_from() -> None:
    assert at(SQL, "c where") == Pointer(None, "c", table=True)


def test_a_column_spelled_through_its_schema() -> None:
    sql = "select sales.customer.personid from sales.customer"
    assert at(sql, "personid") == Pointer("sales.customer", "personid")


def test_quotes_are_kept_for_the_resolver() -> None:
    sql = 'select c."PersonId" from sales.customer c'
    assert at(sql, "PersonId") == Pointer("c", '"PersonId"')


def test_cyrillic_before_the_cursor_does_not_shift_it() -> None:
    sql = "select 'привет', c.personid from sales.customer c"
    assert at(sql, "personid") == Pointer("c", "personid")


@pytest.mark.parametrize("word", ["select", "where", "1"])
def test_keywords_and_literals_point_at_nothing(word: str) -> None:
    assert at(SQL, word) is None


def test_blank_text_points_at_nothing() -> None:
    assert pointer_at("", 0) is None

