from __future__ import annotations

import pytest

from harlequin.references import BufferScope, RelationRef, read_scope


def test_read_scope_finds_aliases_and_bare_relations() -> None:
    sql = """
        with recent as (select * from sales.salesorderheader)
        select c.customerid
        from recent r
        join sales.customer c on r.customerid = c.customerid
        join person.person as p on c.personid = p.personid
        join sales.store on 1 = 1
    """

    scope = read_scope(sql)

    assert scope.relations == (
        RelationRef(name="sales.salesorderheader", alias=None, is_cte=False),
        RelationRef(name="recent", alias="r", is_cte=True),
        RelationRef(name="sales.customer", alias="c", is_cte=False),
        RelationRef(name="person.person", alias="p", is_cte=False),
        RelationRef(name="sales.store", alias=None, is_cte=False),
    )


def test_read_scope_survives_a_broken_buffer() -> None:
    scope = read_scope("select from sales.customer c join")

    assert RelationRef(name="sales.customer", alias="c", is_cte=False) in scope.relations


def test_read_scope_of_empty_text_is_empty() -> None:
    assert read_scope("   ") == BufferScope()


def test_alias_for_matches_by_suffix() -> None:
    scope = read_scope("select 1 from sales.customer c")

    assert scope.alias_for('"retail_training"."sales"."customer"') == "c"


def test_alias_for_matches_a_bare_name() -> None:
    scope = read_scope("select 1 from customer c")

    assert scope.alias_for('"retail_training"."sales"."customer"') == "c"


def test_alias_for_refuses_an_ambiguous_match() -> None:
    scope = read_scope("select 1 from customer c join customer d on 1 = 1")

    assert scope.alias_for('"retail_training"."sales"."customer"') is None


def test_alias_for_ignores_a_relation_without_an_alias() -> None:
    scope = read_scope("select 1 from sales.customer")

    assert scope.alias_for('"retail_training"."sales"."customer"') is None


def test_alias_for_ignores_a_cte_of_the_same_name() -> None:
    scope = read_scope(
        "with customer as (select 1) select 1 from customer c"
    )

    assert scope.alias_for('"retail_training"."sales"."customer"') is None


def test_alias_for_does_not_match_a_different_table() -> None:
    scope = read_scope("select 1 from sales.store s")

    assert scope.alias_for('"retail_training"."sales"."customer"') is None
