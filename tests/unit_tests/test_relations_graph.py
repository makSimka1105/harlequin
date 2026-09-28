from __future__ import annotations

from harlequin.catalog import ForeignKeyEdge
from harlequin.relations.graph import RelationGraph


def edge(
    src: str, src_col: str, dst: str, dst_col: str, nullable: bool = False
) -> ForeignKeyEdge:
    return ForeignKeyEdge(
        constraint_name=f"{src}_{src_col}",
        from_relation=f'"s"."{src}"',
        from_columns=(src_col,),
        to_relation=f'"s"."{dst}"',
        to_columns=(dst_col,),
        nullable=nullable,
    )


GRAPH = RelationGraph(
    [
        edge("orders", "customerid", "customer", "customerid", nullable=True),
        edge("orderline", "orderid", "orders", "orderid"),
        edge("orderline", "productid", "product", "productid"),
    ]
)


def test_links_are_seen_from_both_ends() -> None:
    out = GRAPH.links_for('"s"."orders"')[0]
    assert out.direction == "out"
    assert out.far_relation == '"s"."customer"'
    assert out.cardinality == "N:1"

    [incoming] = GRAPH.links_for('"s"."customer"')
    assert incoming.direction == "in"
    assert incoming.far_relation == '"s"."orders"'
    assert incoming.cardinality == "1:N"


def test_nullable_only_applies_to_the_referencing_end() -> None:
    [out] = [
        link for link in GRAPH.links_for('"s"."orders"') if link.direction == "out"
    ]
    [incoming] = GRAPH.links_for('"s"."customer"')
    assert out.nullable
    assert not incoming.nullable


def test_links_are_sorted_by_far_relation() -> None:
    far = [link.far_relation for link in GRAPH.links_for('"s"."orderline"')]
    assert far == ['"s"."orders"', '"s"."product"']


def test_relation_of_a_column_is_its_table() -> None:
    assert GRAPH.relation_of('"s"."orders"."customerid"') == (
        '"s"."orders"',
        "customerid",
    )
    assert GRAPH.relation_of('"s"."orders"') == ('"s"."orders"', None)
    assert GRAPH.relation_of('"s"."nowhere"') is None


def test_routes_skip_direct_neighbours_and_record_their_source() -> None:
    routes = GRAPH.routes_from('"s"."customer"')
    assert [route.target for route in routes] == [
        '"s"."orderline"',
        '"s"."product"',
    ]
    assert all(route.source == '"s"."customer"' for route in routes)
    assert [len(route) for route in routes] == [2, 3]


def test_a_self_reference_is_a_link_to_itself() -> None:
    graph = RelationGraph([edge("employee", "managerid", "employee", "employeeid")])
    directions = sorted(link.direction for link in graph.links_for('"s"."employee"'))
    assert directions == ["in", "out"]
    assert graph.routes_from('"s"."employee"') == []
