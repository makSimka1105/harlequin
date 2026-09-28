from __future__ import annotations

from harlequin.relations.scope import read_scope

CUSTOMER = '"db"."sales"."customer"'
STORE = '"db"."sales"."store"'


def test_anchor_is_after_the_last_join() -> None:
    sql = (
        "select *\n  from sales.customer c\n"
        "  join sales.store s on s.id = c.id\n  where true"
    )
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("on s.id = c.id")
    assert scope.indent == "  "


def test_anchor_is_after_the_from_relation_without_joins() -> None:
    sql = "select * from sales.customer c, sales.store s where 1 = 1"
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("sales.store s")


def test_no_from_has_no_anchor() -> None:
    assert read_scope("select 1").anchor is None


def test_a_half_written_join_anchors_after_the_from() -> None:
    sql = "select * from sales.customer c\njoin "
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("sales.customer c")


def test_subquery_and_cte_bodies_are_not_top_level() -> None:
    sql = (
        "with r as (select * from sales.store s1) "
        "select * from (select * from sales.store s2) x "
        "join sales.customer c on true"
    )
    top = {ref.name for ref in read_scope(sql).relations if ref.top_level}
    assert top == {"sales.customer"}


def test_anchor_counts_characters_not_bytes() -> None:
    sql = "-- заказы покупателей\nselect * from sales.customer c\nwhere true"
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("sales.customer c")


def test_reference_is_the_alias_or_the_written_name() -> None:
    scope = read_scope("select * from sales.customer c join sales.store on true")
    assert scope.reference_for(CUSTOMER) == "c"
    assert scope.reference_for(STORE) == "sales.store"
    assert scope.position_of(STORE) == 1


def test_reference_ignores_relations_inside_subqueries() -> None:
    scope = read_scope("select * from (select * from sales.store s) x")
    assert scope.reference_for(STORE) is None
    assert scope.alias_for(STORE) == "s"


def test_taken_names_are_aliases_and_bare_table_names() -> None:
    scope = read_scope("select * from sales.customer C join sales.store on true")
    assert scope.taken_names() == {"c", "store"}
