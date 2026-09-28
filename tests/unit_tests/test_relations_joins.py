from __future__ import annotations

import pytest

from harlequin.catalog import ForeignKeyEdge
from harlequin.relations.candidates import join_candidates
from harlequin.relations.graph import Link, RelationGraph, Route
from harlequin.relations.joins import (
    AliasSlot,
    JoinPlan,
    JoinRefusal,
    new_alias,
    plan_joins,
)
from harlequin.relations.scope import read_scope
from harlequin.relations.spelling import DEFAULT_RESERVED


def rel(name: str) -> str:
    return f'"db"."shop"."{name}"'


def edge(
    src: str,
    src_cols: tuple[str, ...],
    dst: str,
    dst_cols: tuple[str, ...],
    nullable: bool = False,
    name: str | None = None,
) -> ForeignKeyEdge:
    return ForeignKeyEdge(
        constraint_name=name or f"{src}_{dst}",
        from_relation=rel(src),
        from_columns=src_cols,
        to_relation=rel(dst),
        to_columns=dst_cols,
        nullable=nullable,
    )


GRAPH = RelationGraph(
    [
        edge("orders", ("customerid",), "customer", ("customerid",), nullable=True),
        edge("orderline", ("orderid",), "orders", ("orderid",)),
        edge("orderline", ("productid",), "product", ("productid",)),
    ]
)


def route(*pairs: tuple[str, str]) -> Route:
    steps: list[Link] = []
    for near, far in pairs:
        [link] = [
            link for link in GRAPH.links_for(rel(near)) if link.far_relation == rel(far)
        ]
        steps.append(link)
    return Route(tuple(steps))


def plan(sql: str, r: Route, aliases: tuple[str, ...] = ()) -> JoinPlan | JoinRefusal:
    return plan_joins(r, read_scope(sql), DEFAULT_RESERVED, aliases=aliases)


def test_one_step_goes_under_the_last_join() -> None:
    sql = (
        "select *\nfrom shop.orders o\njoin shop.orderline ol on ol.orderid = o.orderid"
    )
    result = plan(sql, route(("orders", "customer")))
    assert isinstance(result, JoinPlan)
    assert result.anchor == len(sql)
    assert result.text == "\nleft join shop.customer c on c.customerid = o.customerid"


def test_an_incoming_link_is_an_inner_join() -> None:
    result = plan("select * from shop.customer c", route(("customer", "orders")))
    assert isinstance(result, JoinPlan)
    assert result.text == "\njoin shop.orders o on o.customerid = c.customerid"


def test_a_chain_reuses_a_table_already_in_the_query() -> None:
    sql = "select * from shop.customer c join shop.orders ord on true"
    result = plan(sql, route(("customer", "orders"), ("orders", "orderline")))
    assert isinstance(result, JoinPlan)
    assert result.text == "\njoin shop.orderline o on o.orderid = ord.orderid"


def test_aliases_do_not_collide() -> None:
    sql = "select * from shop.customer c"
    result = plan(sql, route(("customer", "orders"), ("orders", "orderline")))
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "\njoin shop.orders o on o.customerid = c.customerid"
        "\njoin shop.orderline o2 on o2.orderid = o.orderid"
    )


def test_a_composite_key_joins_on_every_column() -> None:
    graph = RelationGraph(
        [edge("line", ("orderid", "lineno"), "orderline", ("orderid", "lineno"))]
    )
    [link] = graph.links_for(rel("line"))
    result = plan_joins(
        Route((link,)), read_scope("select * from shop.line l"), DEFAULT_RESERVED
    )
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "\njoin shop.orderline o on o.orderid = l.orderid and o.lineno = l.lineno"
    )


def test_a_self_reference_gets_its_own_alias() -> None:
    graph = RelationGraph(
        [edge("employee", ("managerid",), "employee", ("employeeid",), nullable=True)]
    )
    [out] = [
        link for link in graph.links_for(rel("employee")) if link.direction == "out"
    ]
    result = plan_joins(
        Route((out,)), read_scope("select * from shop.employee e"), DEFAULT_RESERVED
    )
    assert isinstance(result, JoinPlan)
    assert result.text == "\nleft join shop.employee e2 on e2.employeeid = e.managerid"


def test_without_a_from_the_plan_starts_with_one() -> None:
    result = plan("select 1", route(("customer", "orders")))
    assert result == JoinPlan(
        anchor=None,
        text="from shop.customer c\njoin shop.orders o on o.customerid = c.customerid",
        aliases=(AliasSlot(rel("customer"), "c"), AliasSlot(rel("orders"), "o")),
    )


def test_a_query_without_the_source_is_refused() -> None:
    result = plan("select * from shop.product p", route(("customer", "orders")))
    assert result == JoinRefusal("customer нет в запросе")


def test_a_route_already_in_the_query_is_refused() -> None:
    sql = "select * from shop.customer c join shop.orders o on true"
    assert isinstance(plan(sql, route(("customer", "orders"))), JoinRefusal)


def test_new_alias_abbreviates_snake_case_and_skips_reserved() -> None:
    taken: set[str] = set()
    assert new_alias(rel("sales_order"), taken, DEFAULT_RESERVED) == "so"
    assert new_alias(rel("sales_order"), taken, DEFAULT_RESERVED) == "so2"
    assert new_alias(rel("as"), set(), frozenset({"a"})) == "a2"


def test_candidates_cover_every_table_in_the_query() -> None:
    scope = read_scope("select * from shop.customer c join shop.orders o on true")
    candidates = join_candidates(scope, GRAPH)
    assert [r.target for r in candidates] == [rel("orderline"), rel("product")]
    assert [len(r) for r in candidates] == [1, 2]


def test_two_keys_to_the_same_table_stay_separate_candidates() -> None:
    graph = RelationGraph(
        [
            edge("orders", ("billto",), "address", ("addressid",), name="bill"),
            edge("orders", ("shipto",), "address", ("addressid",), name="ship"),
        ]
    )
    candidates = join_candidates(read_scope("select * from shop.orders o"), graph)
    assert [r.steps[0].near_columns for r in candidates] == [("billto",), ("shipto",)]


ADDRESS_GRAPH = RelationGraph(
    [
        edge("orders", ("billto",), "address", ("addressid",), name="bill"),
        edge("orders", ("shipto",), "address", ("addressid",), name="ship"),
        edge("address", ("stateid",), "state", ("stateid",)),
    ]
)
BILLED = "select * from shop.orders o join shop.address a on a.addressid = o.billto"


def address_link(column: str) -> Link:
    [link] = [
        link
        for link in ADDRESS_GRAPH.links_for(rel("orders"))
        if link.near_columns == (column,)
    ]
    return link


def test_a_second_key_to_a_joined_table_joins_it_again() -> None:
    [to_state] = [
        link
        for link in ADDRESS_GRAPH.links_for(rel("address"))
        if link.far_relation == rel("state")
    ]
    result = plan_joins(
        Route((address_link("shipto"), to_state)),
        read_scope(BILLED),
        DEFAULT_RESERVED,
        graph=ADDRESS_GRAPH,
    )
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "\njoin shop.address a2 on a2.addressid = o.shipto"
        "\njoin shop.state s on s.stateid = a2.stateid"
    )


def test_the_other_key_to_a_joined_table_stays_a_candidate() -> None:
    candidates = join_candidates(read_scope(BILLED), ADDRESS_GRAPH)
    columns = [r.steps[0].near_columns for r in candidates if len(r) == 1]
    assert ("shipto",) in columns


def test_a_table_joined_to_itself_is_still_a_source() -> None:
    graph = RelationGraph(
        [
            edge("employee", ("managerid",), "employee", ("employeeid",)),
            edge("employee", ("deptid",), "dept", ("deptid",)),
        ]
    )
    sql = (
        "select * from shop.employee e "
        "join shop.employee e2 on e2.employeeid = e.managerid"
    )
    [to_dept] = [
        link
        for link in graph.links_for(rel("employee"))
        if link.far_relation == rel("dept")
    ]
    result = plan_joins(Route((to_dept,)), read_scope(sql), DEFAULT_RESERVED)
    assert isinstance(result, JoinPlan)
    assert result.text == "\njoin shop.dept d on d.deptid = e.deptid"
    assert rel("dept") in [r.target for r in join_candidates(read_scope(sql), graph)]


CHAIN = route(("customer", "orders"), ("orders", "orderline"))


def test_chosen_aliases_replace_the_generated_ones_everywhere() -> None:
    result = plan("select * from shop.customer c", CHAIN, ("ord", "line"))
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "\njoin shop.orders ord on ord.customerid = c.customerid"
        "\njoin shop.orderline line on line.orderid = ord.orderid"
    )
    assert [slot.alias for slot in result.aliases] == ["ord", "line"]


def test_a_blank_choice_keeps_the_generated_alias() -> None:
    result = plan("select * from shop.customer c", CHAIN, ("", "line"))
    assert isinstance(result, JoinPlan)
    assert [slot.alias for slot in result.aliases] == ["o", "line"]


def test_the_source_alias_is_the_first_choice_without_a_from() -> None:
    result = plan("select 1", route(("customer", "orders")), ("cust", "ord"))
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "from shop.customer cust"
        "\njoin shop.orders ord on ord.customerid = cust.customerid"
    )


@pytest.mark.parametrize(
    ("aliases", "refusal"),
    [
        (("c", ""), JoinRefusal("c уже занят", slot=0)),
        (("ord", "ord"), JoinRefusal("ord уже занят", slot=1)),
        (("", "select"), JoinRefusal("select — ключевое слово", slot=1)),
        (("1o", ""), JoinRefusal("1o — не имя", slot=0)),
    ],
)
def test_an_unusable_choice_is_refused_at_its_slot(
    aliases: tuple[str, ...], refusal: JoinRefusal
) -> None:
    assert plan("select * from shop.customer c", CHAIN, aliases) == refusal
