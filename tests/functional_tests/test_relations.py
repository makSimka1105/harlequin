from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

import duckdb
import pytest
from rich.console import Console
from textual.pilot import Pilot
from textual.widgets import Input, OptionList
from textual.widgets.text_area import Selection

from harlequin import Harlequin
from harlequin.adapter import HarlequinAdapter
from harlequin.app import SchemaReady
from harlequin.catalog import ColumnDetails, ForeignKeyEdge
from harlequin.components.code_editor import CodeEditor
from harlequin.components.join_picker import JoinPicker
from harlequin.relations.graph import RelationGraph
from harlequin.relations.schema import SchemaIndex
from harlequin.relations_service import Focus
from tests.functional_tests.helpers import wait_for_catalog_tree, wait_for_editor
from tests.waiting import wait_for

WaitForWorkers = Callable[[Harlequin], Awaitable[None]]

SHOP_SQL = """
create table customer(customerid int primary key, name varchar);
create table orders(
    orderid int primary key, customerid int references customer(customerid)
);
create table orderline(orderid int references orders(orderid), qty int);
"""


def shop(name: str) -> str:
    return f'"shop"."main"."{name}"'


def shop_edge(
    src: str, column: str, dst: str, nullable: bool = False
) -> ForeignKeyEdge:
    return ForeignKeyEdge(
        constraint_name=f"{src}_{dst}",
        from_relation=shop(src),
        from_columns=(column,),
        to_relation=shop(dst),
        to_columns=(column,),
        database="shop",
        nullable=nullable,
    )


def shop_column(
    table: str, name: str, position: int, primary_key: bool = False
) -> ColumnDetails:
    return ColumnDetails(
        relation=shop(table),
        name=name,
        position=position,
        type_name="INTEGER",
        nullable=not primary_key,
        default=None,
        primary_key=primary_key,
        unique=False,
        indexed=primary_key,
        comment=None,
        database="shop",
    )


SHOP_GRAPH = RelationGraph(
    [
        shop_edge("orders", "customerid", "customer", nullable=True),
        shop_edge("orderline", "orderid", "orders"),
    ]
)
SHOP_SCHEMA = SchemaIndex(
    [
        shop_column("customer", "customerid", 1, primary_key=True),
        shop_column("customer", "name", 2),
        shop_column("orders", "orderid", 1, primary_key=True),
        shop_column("orders", "customerid", 2),
        shop_column("orderline", "orderid", 1),
        shop_column("orderline", "qty", 2),
    ]
)


@pytest.fixture
def app_shop(duckdb_adapter: type[HarlequinAdapter], tmp_path: Path) -> Harlequin:
    path = tmp_path / "shop.db"
    conn = duckdb.connect(str(path))
    conn.execute(SHOP_SQL)
    conn.close()
    return Harlequin(duckdb_adapter([str(path)], no_init=True), connection_hash="shop")


async def ready(
    pilot: Pilot, app: Harlequin, wait_for_workers: WaitForWorkers
) -> CodeEditor:
    await wait_for_workers(app)
    editor = await wait_for_editor(pilot, app)
    await wait_for_catalog_tree(pilot, app)
    # the catalog starts its own schema read; ours has to land after it
    await wait_for_workers(app)
    app.post_message(SchemaReady(graph=SHOP_GRAPH, schema=SHOP_SCHEMA))
    await wait_for(
        pilot,
        lambda: app.inspector.schema is SHOP_SCHEMA,
        description="the shop schema to reach the Inspector",
    )
    return editor


def put(editor: CodeEditor, text: str, cursor: tuple[int, int]) -> None:
    editor.text = text
    editor.selection = Selection(cursor, cursor)


def row_texts(app: Harlequin) -> list[str]:
    rows = app.inspector.rows
    console = Console(width=40, color_system=None)
    texts = []
    for index in range(rows.option_count):
        with console.capture() as captured:
            console.print(rows.get_option_at_index(index).prompt)
        texts.append(" ".join(captured.get().split()).rstrip("─ "))
    return texts


async def inspect(pilot: Pilot, app: Harlequin, focus: Focus) -> None:
    app.inspector.show(focus, "shop")
    app.inspector.rows.focus()
    await pilot.pause()


@pytest.mark.asyncio
async def test_a_table_lists_its_columns_then_its_links(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await ready(pilot, app_shop, wait_for_workers)
        await inspect(pilot, app_shop, Focus(shop("orders")))

        assert row_texts(app_shop) == [
            "PK orderid INTEGER",
            "FK customerid INTEGER?",
            "─ ссылается на · 1",
            "→ customer ?",
            "─ ссылаются сюда · 1",
            "← orderline",
        ]
        assert app_shop.inspector.border_title == "main.orders · 2 кол · 2 св"
        assert app_shop.inspector.rows.highlighted == 0


@pytest.mark.asyncio
async def test_a_column_is_highlighted_with_its_keys_under_the_panel(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await ready(pilot, app_shop, wait_for_workers)
        await inspect(pilot, app_shop, Focus(shop("orders"), "customerid"))

        assert app_shop.inspector.rows.highlighted == 1
        assert app_shop.inspector.border_subtitle == "null"


@pytest.mark.asyncio
async def test_the_inspector_follows_the_editor_cursor_through_an_alias(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        editor.focus()
        put(editor, "select o.customerid from main.orders o", (0, 12))

        await wait_for(
            pilot,
            lambda: app_shop.inspector.target == Focus(shop("orders"), "customerid"),
            description="the Inspector to show o.customerid",
        )
        assert app_shop.inspector.rows.highlighted == 1


@pytest.mark.asyncio
async def test_the_inspector_keeps_its_pick_while_it_has_focus(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select o.customerid from main.orders o", (0, 12))
        await inspect(pilot, app_shop, Focus(shop("customer")))

        await pilot.pause(0.3)
        assert app_shop.inspector.target == Focus(shop("customer"))


@pytest.mark.asyncio
async def test_enter_inserts_the_highlighted_column(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select * from main.orders o where ", (0, 34))
        await inspect(pilot, app_shop, Focus(shop("orders"), "customerid"))

        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: editor.text == "select * from main.orders o where o.customerid",
            description="the column to be inserted under its alias",
        )


@pytest.mark.asyncio
async def test_enter_on_a_link_inserts_the_table_under_its_alias(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select * from main.customer cu where ", (0, 37))
        await inspect(pilot, app_shop, Focus(shop("orders")))

        await pilot.press("j", "j", "enter")
        await wait_for(
            pilot,
            lambda: editor.text == "select * from main.customer cu where cu",
            description="the customer alias to be inserted",
        )


@pytest.mark.asyncio
async def test_a_new_schema_keeps_what_the_inspector_shows(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await ready(pilot, app_shop, wait_for_workers)
        await inspect(pilot, app_shop, Focus(shop("orders"), "customerid"))

        app_shop.post_message(SchemaReady(graph=SHOP_GRAPH, schema=SHOP_SCHEMA))
        await pilot.pause()
        assert app_shop.inspector.target == Focus(shop("orders"), "customerid")
        assert app_shop.inspector.rows.highlighted == 1


CUSTOMER_SQL = "select *\nfrom main.customer c"


async def open_picker(
    pilot: Pilot, app: Harlequin, wait_for_workers: WaitForWorkers
) -> CodeEditor:
    editor = await ready(pilot, app, wait_for_workers)
    put(editor, CUSTOMER_SQL, (1, 5))
    app.action_show_join_picker()
    await pilot.pause()
    assert isinstance(app.screen, JoinPicker)
    return editor


async def pick_orderline(pilot: Pilot) -> None:
    await pilot.press("l", "i", "n", "e", "enter")
    await pilot.pause()


def alias_inputs(app: Harlequin) -> list[Input]:
    return list(app.screen.query("#join_aliases Input").results(Input))


@pytest.mark.asyncio
async def test_picker_filters_and_inserts_a_chain_as_is(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await open_picker(pilot, app_shop, wait_for_workers)

        await pilot.press("l", "i", "n", "e")
        options = app_shop.screen.query_one("#join_candidates", OptionList)
        assert options.option_count == 1
        await pilot.press("ctrl+enter")
        await pilot.pause()

        assert editor.text == (
            CUSTOMER_SQL + "\njoin main.orders o on o.customerid = c.customerid"
            "\njoin main.orderline o2 on o2.orderid = o.orderid"
        )


@pytest.mark.asyncio
async def test_enter_steps_through_the_new_aliases(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await open_picker(pilot, app_shop, wait_for_workers)
        await pick_orderline(pilot)

        first, second = alias_inputs(app_shop)
        assert first.has_focus and first.value == "o"
        assert app_shop.screen.query_one("#join_picker").border_title == (
            "Join › алиасы ●○ 1/2"
        )
        await pilot.press("o", "r", "d", "enter")
        assert second.has_focus
        assert second.parent is not None and second.parent.has_class("-current")
        await pilot.press("l", "n", "enter")
        await pilot.pause()

        assert editor.text == (
            CUSTOMER_SQL + "\njoin main.orders ord on ord.customerid = c.customerid"
            "\njoin main.orderline ln on ln.orderid = ord.orderid"
        )


@pytest.mark.asyncio
async def test_shift_tab_goes_back_to_rename_again(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await open_picker(pilot, app_shop, wait_for_workers)
        await pick_orderline(pilot)

        await pilot.press("x", "enter", "shift+tab")
        first, _ = alias_inputs(app_shop)
        assert first.has_focus
        await pilot.press("o", "r", "d", "enter", "enter")
        await pilot.pause()

        assert "join main.orders ord on" in editor.text


@pytest.mark.asyncio
async def test_a_taken_alias_blocks_the_insert(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await open_picker(pilot, app_shop, wait_for_workers)
        await pick_orderline(pilot)

        await pilot.press("c", "enter", "enter")
        await pilot.pause()

        assert isinstance(app_shop.screen, JoinPicker)
        assert app_shop.screen.query_one("#join_picker").border_subtitle == (
            "c уже занят"
        )
        first, _ = alias_inputs(app_shop)
        assert first.has_class("-invalid")
        assert editor.text == CUSTOMER_SQL


@pytest.mark.asyncio
async def test_escape_from_the_aliases_returns_to_the_routes(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await open_picker(pilot, app_shop, wait_for_workers)
        await pick_orderline(pilot)

        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app_shop.screen, JoinPicker)
        assert app_shop.screen.query_one("#join_candidates").display
        assert not app_shop.screen.query_one("#join_aliases").display
        assert app_shop.screen.query_one("#join_filter", Input).value == "line"


@pytest.mark.asyncio
@pytest.mark.parametrize("screen_height", [40, 41])
async def test_the_picker_keeps_its_top_while_routes_change_height(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers, screen_height: int
) -> None:
    async with app_shop.run_test(size=(140, screen_height)) as pilot:
        await open_picker(pilot, app_shop, wait_for_workers)
        box = app_shop.screen.query_one("#join_picker")
        top, height = box.region.y, box.region.height

        await pilot.press("down")
        await pilot.pause()

        assert box.region.height != height
        assert box.region.y == top


@pytest.mark.asyncio
async def test_picker_escape_changes_nothing(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select * from main.customer c", (0, 3))

        app_shop.action_show_join_picker()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app_shop.screen, JoinPicker)
        assert editor.text == "select * from main.customer c"


@pytest.mark.asyncio
async def test_the_footer_lists_the_inspector_keys(
    app_shop: Harlequin, wait_for_workers: WaitForWorkers
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await ready(pilot, app_shop, wait_for_workers)
        await inspect(pilot, app_shop, Focus(shop("orders")))

        shown = {
            key
            for key, active in app_shop.screen.active_bindings.items()
            if active.binding.show and active.node is app_shop.inspector
        }
        assert shown == {"j", "k", "enter"}
