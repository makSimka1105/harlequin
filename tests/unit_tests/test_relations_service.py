from __future__ import annotations

from harlequin.catalog import Catalog, CatalogItem, ColumnDetails, ForeignKeyEdge
from harlequin.relations.graph import RelationGraph, Route
from harlequin.relations.joins import JoinRefusal
from harlequin.relations.schema import SchemaIndex
from harlequin.relations_service import Edit, Focus, RelationsService
from harlequin.statements import StatementSpan


def item(identifier: str, query_name: str, children: list[CatalogItem]) -> CatalogItem:
    return CatalogItem(
        qualified_identifier=identifier,
        query_name=query_name,
        label=identifier.rsplit(".", 1)[-1].strip('"'),
        type_label="t",
        children=children,
    )


CUSTOMERID = item('"db"."shop"."customer"."customerid"', '"customerid"', [])
CUSTOMER = item('"db"."shop"."customer"', '"shop"."customer"', [CUSTOMERID])
ORDERS = item('"db"."shop"."orders"', '"shop"."orders"', [])
CATALOG = Catalog(
    items=[item('"db"', '"db"', [item('"db"."shop"', '"shop"', [CUSTOMER, ORDERS])])]
)
EDGE = ForeignKeyEdge(
    constraint_name="orders_customer",
    from_relation='"db"."shop"."orders"',
    from_columns=("customerid",),
    to_relation='"db"."shop"."customer"',
    to_columns=("customerid",),
    nullable=True,
)


def service() -> RelationsService:
    relations = RelationsService(on_loaded=lambda parent, children: None)
    relations.update_catalog(CATALOG)
    relations.graph = RelationGraph([EDGE])
    return relations


def orders_to_customer(relations: RelationsService) -> Route:
    [link] = [
        link
        for link in relations.graph.links_for('"db"."shop"."orders"')
        if link.direction == "out"
    ]
    return Route((link,))


def test_path_text_uses_the_alias_in_the_statement() -> None:
    text = service().path_text(
        '"db"."shop"."customer"."customerid"', "db", "select * from shop.customer c"
    )
    assert text == "c.customerid"


def test_path_text_of_an_unknown_identifier_is_none() -> None:
    assert service().path_text('"db"."shop"."nope"', "db", "") is None


def test_known_relations_are_the_loaded_tables() -> None:
    known = service().lookup.known_relations()
    assert known == frozenset({'"db"."shop"."customer"', '"db"."shop"."orders"'})


def test_join_edit_is_an_absolute_offset() -> None:
    relations = service()
    statement = StatementSpan(start=10, text="select * from shop.orders o")
    edit = relations.join_edit(orders_to_customer(relations), statement)
    assert edit == Edit(
        offset=10 + len(statement.text),
        text="\nleft join shop.customer c on c.customerid = o.customerid",
    )


def test_join_edit_in_an_empty_buffer_starts_a_from_at_the_cursor() -> None:
    relations = service()
    edit = relations.join_edit(orders_to_customer(relations), None)
    assert edit == Edit(
        offset=None,
        text=(
            "from shop.orders o\n"
            "left join shop.customer c on c.customerid = o.customerid"
        ),
    )


def test_join_edit_refuses_a_query_without_the_source() -> None:
    relations = service()
    edit = relations.join_edit(
        orders_to_customer(relations), StatementSpan(0, "select * from shop.x x")
    )
    assert isinstance(edit, JoinRefusal)


def test_candidates_carry_the_source_reference_and_a_preview() -> None:
    [candidate] = service().join_candidates(
        StatementSpan(0, "select * from shop.orders o")
    )
    assert candidate.source == "o"
    assert candidate.preview == (
        "left join shop.customer c on c.customerid = o.customerid"
    )
    assert [slot.alias for slot in candidate.aliases] == ["c"]


def test_join_edit_takes_the_chosen_aliases() -> None:
    relations = service()
    statement = StatementSpan(start=0, text="select * from shop.orders o")
    edit = relations.join_edit(orders_to_customer(relations), statement, ["cust"])
    assert edit == Edit(
        offset=len(statement.text),
        text="\nleft join shop.customer cust on cust.customerid = o.customerid",
    )


def test_join_edit_without_from_goes_after_the_statement_not_mid_word() -> None:
    relations = service()
    edit = relations.join_edit(
        orders_to_customer(relations), StatementSpan(4, "select *")
    )
    assert isinstance(edit, Edit)
    assert edit.offset == 4 + len("select *")
    assert edit.text.startswith("\nfrom shop.orders o")


def details(relation: str, name: str, position: int) -> ColumnDetails:
    return ColumnDetails(
        relation=relation,
        name=name,
        position=position,
        type_name="int",
        nullable=True,
        default=None,
        primary_key=False,
        unique=False,
        indexed=False,
        comment=None,
    )


ORDERS_ID = '"db"."shop"."orders"'
CUSTOMER_ID = '"db"."shop"."customer"'
JOINED = (
    "select o.customerid, name from shop.orders o "
    "join shop.customer c on c.customerid = o.customerid"
)


def inspecting() -> RelationsService:
    relations = service()
    relations.schema = SchemaIndex(
        [
            details(ORDERS_ID, "orderid", 1),
            details(ORDERS_ID, "customerid", 2),
            details(CUSTOMER_ID, "customerid", 1),
            details(CUSTOMER_ID, "name", 2),
        ]
    )
    return relations


def focus(sql: str, word: str, start: int = 0) -> Focus | None:
    return inspecting().focus_at(StatementSpan(start, sql), start + sql.index(word) + 1)


def test_an_aliased_column_is_found_through_the_alias() -> None:
    assert focus(JOINED, "customerid") == Focus(ORDERS_ID, "customerid")


def test_a_bare_column_owned_by_one_table_is_found() -> None:
    assert focus(JOINED, "name") == Focus(CUSTOMER_ID, "name")


def test_a_bare_column_two_tables_share_is_not_guessed() -> None:
    sql = "select customerid from shop.orders o join shop.customer c on true"
    assert focus(sql, "customerid") is None


def test_an_alias_is_its_table() -> None:
    assert focus(JOINED, "c on") == Focus(CUSTOMER_ID)


def test_a_table_written_with_its_schema() -> None:
    assert focus(JOINED, "shop.customer") == Focus(CUSTOMER_ID)


def test_the_statement_offset_is_taken_off_the_cursor() -> None:
    assert focus(JOINED, "name", start=40) == Focus(CUSTOMER_ID, "name")


def test_an_unknown_alias_points_at_nothing() -> None:
    assert focus("select z.customerid from shop.orders o", "customerid") is None


def test_a_column_the_schema_does_not_list_falls_back_to_its_table() -> None:
    assert focus("select o.nope from shop.orders o", "nope") == Focus(ORDERS_ID)


def test_a_table_without_details_still_names_the_column() -> None:
    relations = service()
    sql = "select o.customerid from shop.orders o"
    assert relations.focus_at(StatementSpan(0, sql), sql.index("customerid")) == Focus(
        ORDERS_ID, "customerid"
    )


def test_a_catalog_identifier_is_a_table_or_one_of_its_columns() -> None:
    relations = inspecting()
    assert relations.focus_on(ORDERS_ID) == Focus(ORDERS_ID)
    assert relations.focus_on(f'{ORDERS_ID}."orderid"') == Focus(ORDERS_ID, "orderid")
    assert relations.focus_on('"db"."shop"') is None
