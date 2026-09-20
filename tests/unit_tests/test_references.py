from __future__ import annotations

from harlequin.catalog import CatalogItem
from harlequin.references import (
    DEFAULT_RESERVED,
    BufferScope,
    RelationRef,
    path_for,
    read_scope,
)


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
    # a dangling `on` is what a buffer looks like mid-join. An empty select
    # list is not a shape to test here: the grammar recovers no from-clause
    # at all without one, so no relation node exists to find.
    scope = read_scope("select 1 from sales.customer c join person.person p on")

    assert (
        RelationRef(name="sales.customer", alias="c", is_cte=False) in scope.relations
    )
    assert (
        RelationRef(name="person.person", alias="p", is_cte=False) in scope.relations
    )


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


def _relation(schema: str, table: str) -> CatalogItem:
    return CatalogItem(
        qualified_identifier=f'"retail_training"."{schema}"."{table}"',
        query_name=f'"{schema}"."{table}"',
        label=table,
        type_label="t",
    )


def _column(schema: str, table: str, column: str) -> CatalogItem:
    return CatalogItem(
        qualified_identifier=f'"retail_training"."{schema}"."{table}"."{column}"',
        query_name=f'"{column}"',
        label=column,
        type_label="##",
    )


def test_path_for_column_without_the_table_in_the_buffer() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "sales.customer.customerid"


def test_path_for_column_uses_the_alias_when_there_is_one() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select 1 from sales.customer c"),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "c.customerid"


def test_path_for_column_ignores_an_unaliased_table() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select 1 from sales.customer"),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "sales.customer.customerid"


def test_path_for_relation_is_already_qualified() -> None:
    result = path_for(
        item=_relation("sales", "customer"),
        owner=None,
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "sales.customer"


def test_path_for_relation_collapses_to_its_alias() -> None:
    result = path_for(
        item=_relation("sales", "customer"),
        owner=None,
        scope=read_scope("select 1 from sales.customer c"),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "c"


def test_path_for_keeps_quotes_around_an_unsafe_identifier() -> None:
    result = path_for(
        item=_column("sales", "customer", "Order Date"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == 'sales.customer."Order Date"'


def test_path_for_keeps_quotes_around_a_reserved_word() -> None:
    result = path_for(
        item=_column("sales", "customer", "order"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == 'sales.customer."order"'


def test_path_for_without_an_owner_falls_back_to_the_query_name() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=None,
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "customerid"
