"""The table or column under the cursor: its columns, keys and links."""

from __future__ import annotations

from typing import Union

from rich.console import RenderableType
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from harlequin.catalog import ColumnDetails
from harlequin.relations.graph import Direction, Link, RelationGraph
from harlequin.relations.schema import SchemaIndex
from harlequin.relations.spelling import split_identifier, table_name
from harlequin.relations_service import Focus

DIM = Style(dim=True)
BOLD = Style(bold=True)
TYPE_WIDTH = 11
LINK_GROUPS: tuple[tuple[Direction, str], ...] = (
    ("out", "ссылается на"),
    ("in", "ссылаются сюда"),
)
SHORT_TYPES = {
    "character varying": "varchar",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamptz",
    "time without time zone": "time",
    "double precision": "float8",
    "character": "char",
}
MOVE = Binding.Group("Move", compact=True)

Entry = Union[ColumnDetails, Link, None]


class InspectorPanel(Vertical):
    BORDER_TITLE = "Inspector"

    BINDINGS = [
        Binding("j", "move(1)", "Down", group=MOVE),
        Binding("k", "move(-1)", "Up", group=MOVE),
        # the list owns enter; claiming it first is what puts it in the footer
        Binding("enter", "select", "Insert", priority=True),
    ]

    class InsertPath(Message):
        def __init__(self, identifier: str, database: str | None) -> None:
            super().__init__()
            self.identifier = identifier
            self.database = database

    def __init__(self) -> None:
        super().__init__(id="inspector_panel")
        self.graph = RelationGraph(())
        self.schema = SchemaIndex(())
        self.target: Focus | None = None
        self._database: str | None = None
        self._entries: list[Entry] = []

    def compose(self) -> ComposeResult:
        yield OptionList(id="inspector_rows")

    def on_mount(self) -> None:
        self._refresh_rows()

    @property
    def rows(self) -> OptionList:
        return self.query_one("#inspector_rows", OptionList)

    def update_schema(self, graph: RelationGraph, schema: SchemaIndex) -> None:
        self.graph = graph
        self.schema = schema
        self._refresh_rows()

    def show(self, target: Focus | None, database: str | None = None) -> None:
        same_table = (
            target is not None
            and self.target is not None
            and target.relation == self.target.relation
        )
        self.target = target
        self._database = database
        if same_table:
            self._highlight_target()
        else:
            self._refresh_rows()

    def action_move(self, delta: int) -> None:
        if delta > 0:
            self.rows.action_cursor_down()
        else:
            self.rows.action_cursor_up()

    def action_select(self) -> None:
        self.rows.action_select()

    @on(OptionList.OptionHighlighted, "#inspector_rows")
    def _row_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._show_detail(self._entry_at(event.option_index))

    @on(OptionList.OptionSelected, "#inspector_rows")
    def _row_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        entry = self._entry_at(event.option_index)
        if isinstance(entry, ColumnDetails):
            identifier = f'{entry.relation}."{entry.name}"'
        elif isinstance(entry, Link):
            identifier = entry.far_relation
        else:
            return
        self.post_message(self.InsertPath(identifier, self._database))

    def _refresh_rows(self) -> None:
        if not self.is_mounted:
            return
        rows = self.rows
        rows.clear_options()
        self._entries = []
        if self.target is None:
            self.border_title = self.BORDER_TITLE
            self._note("выбери таблицу или поле")
            self._show_detail(None)
            return

        relation = self.target.relation
        columns = self.schema.columns_of(relation)
        links = self.graph.links_for(relation)
        self.border_title = _title(relation, len(columns), len(links))
        for column in columns:
            self._add(Option(_column_label(column, links)), column)
        for direction, heading in LINK_GROUPS:
            group = [link for link in links if link.direction == direction]
            if not group:
                continue
            rule = Rule(Text(f"─ {heading} · {len(group)}", DIM), align="left")
            self._add(Option(rule, disabled=True), None)
            for link in group:
                self._add(Option(_link_label(link)), link)
        if not self._entries:
            self._note("нет данных о схеме")
        self._highlight_target()

    def _highlight_target(self) -> None:
        column = self.target.column if self.target is not None else None
        selectable = [
            index for index, entry in enumerate(self._entries) if entry is not None
        ]
        index = next(
            (
                index
                for index in selectable
                if isinstance(entry := self._entries[index], ColumnDetails)
                and entry.name == column
            ),
            selectable[0] if selectable else None,
        )
        self.rows.highlighted = index
        self._show_detail(self._entry_at(index))

    def _show_detail(self, entry: Entry) -> None:
        self.border_subtitle = (
            _column_detail(entry) if isinstance(entry, ColumnDetails) else ""
        )

    def _add(self, option: Option, entry: Entry) -> None:
        self.rows.add_option(option)
        self._entries.append(entry)

    def _entry_at(self, index: int | None) -> Entry:
        if index is None or not 0 <= index < len(self._entries):
            return None
        return self._entries[index]

    def _note(self, message: str) -> None:
        self._add(Option(Text(message, DIM), disabled=True), None)


def _title(relation: str, column_count: int, link_count: int) -> str:
    counts = [
        f"{count} {unit}"
        for count, unit in ((column_count, "кол"), (link_count, "св"))
        if count
    ]
    return " · ".join([".".join(split_identifier(relation)[-2:]), *counts])


def _row(*cells: RenderableType) -> Table:
    """One line that fits the panel: the middle cell gives way with an ellipsis."""
    grid = Table.grid(expand=True, padding=(0, 1), pad_edge=False)
    grid.add_column(width=2, no_wrap=True)
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(*cells)
    return grid


def _column_label(column: ColumnDetails, links: list[Link]) -> Table:
    foreign = any(
        link.direction == "out" and column.name in link.near_columns for link in links
    )
    mark = next(
        (
            mark
            for mark, present in (
                ("PK", column.primary_key),
                ("FK", foreign),
                ("UQ", column.unique),
            )
            if present
        ),
        "",
    )
    type_label = _short_type(column.type_name) + ("?" if column.nullable else "")
    return _row(Text(mark, BOLD), column.name, Text(type_label, DIM))


def _link_label(link: Link) -> Table:
    arrow = "→" if link.direction == "out" else "←"
    return _row(
        Text(arrow, BOLD),
        table_name(link.far_relation),
        Text("?" if link.nullable else "", DIM),
    )


def _column_detail(column: ColumnDetails) -> str:
    flags = [
        flag
        for flag, present in (
            ("pk", column.primary_key),
            ("uq", column.unique),
            ("index", column.indexed),
        )
        if present
    ]
    default = [f"default {column.default}"] if column.default is not None else []
    return " · ".join(["null" if column.nullable else "not null", *flags, *default])


def _short_type(type_name: str) -> str:
    base, paren, rest = type_name.partition("(")
    short = SHORT_TYPES.get(base, base) + paren + rest
    return short if len(short) <= TYPE_WIDTH else short[: TYPE_WIDTH - 1] + "…"
