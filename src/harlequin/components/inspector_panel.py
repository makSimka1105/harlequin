"""The table or column under the cursor: its columns, keys and links."""

from __future__ import annotations

from typing import Union

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from harlequin.catalog import ColumnDetails
from harlequin.components.join_picker import route_label
from harlequin.relations.graph import Link, RelationGraph, Route
from harlequin.relations.schema import SchemaIndex
from harlequin.relations.spelling import split_identifier, table_name
from harlequin.relations_service import Focus

DIM = Style(dim=True)
BOLD = Style(bold=True)
MAX_NAME_WIDTH = 20
TYPE_WIDTH = 11
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
        yield Static(id="inspector_title")
        yield OptionList(id="inspector_rows")
        yield Static(id="inspector_detail")

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
        title = self.query_one("#inspector_title", Static)
        if self.target is None:
            title.update("")
            self._note("выбери таблицу или поле")
            self._show_detail(None)
            return

        relation = self.target.relation
        title.update(Text(_display_name(relation), BOLD))
        columns = self.schema.columns_of(relation)
        links = self.graph.links_for(relation)
        width = min(
            max((len(column.name) for column in columns), default=0), MAX_NAME_WIDTH
        )
        for column in columns:
            self._add(Option(_column_label(column, links, width)), column)
        if columns and links:
            self._add(Option(Text("связи", DIM), disabled=True), None)
        for link in links:
            self._add(Option(route_label(Route((link,)))), link)
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
        detail = self.query_one("#inspector_detail", Static)
        detail.display = entry is not None
        if isinstance(entry, ColumnDetails):
            detail.update(self._column_detail(entry))
        elif isinstance(entry, Link):
            detail.update(_link_detail(entry))

    def _column_detail(self, column: ColumnDetails) -> Text:
        lines = [
            Text.assemble(
                column.type_name, (" · NULL" if column.nullable else " · NOT NULL", DIM)
            )
        ]
        keys = [
            label
            for label, present in (
                ("primary key", column.primary_key),
                ("unique", column.unique),
                ("index", column.indexed),
            )
            if present
        ]
        if column.default is not None:
            keys.append(f"default {column.default}")
        if keys:
            lines.append(Text(" · ".join(keys)))
        for link in self.graph.links_for(column.relation):
            if column.name not in link.near_columns:
                continue
            far_column = link.far_columns[link.near_columns.index(column.name)]
            arrow = "→" if link.direction == "out" else "←"
            lines.append(Text(f"{arrow} {table_name(link.far_relation)}.{far_column}"))
        if column.comment:
            lines.append(Text(column.comment, DIM))
        return Text("\n").join(lines)

    def _add(self, option: Option, entry: Entry) -> None:
        self.rows.add_option(option)
        self._entries.append(entry)

    def _entry_at(self, index: int | None) -> Entry:
        if index is None or not 0 <= index < len(self._entries):
            return None
        return self._entries[index]

    def _note(self, message: str) -> None:
        self._add(Option(Text(message, DIM), disabled=True), None)


def _display_name(relation: str) -> str:
    return ".".join(split_identifier(relation)[-2:])


def _column_label(column: ColumnDetails, links: list[Link], width: int) -> Text:
    foreign = any(
        link.direction == "out" and column.name in link.near_columns for link in links
    )
    marks = [
        mark
        for mark, present in (
            ("PK", column.primary_key),
            ("FK", foreign),
            ("UQ", column.unique),
        )
        if present
    ]
    return Text.assemble(
        f"{column.name:<{width}} ",
        (f"{_short_type(column.type_name):<{TYPE_WIDTH}} ", DIM),
        (" ".join(marks), BOLD),
        ("?" if column.nullable else "", DIM),
    )


def _short_type(type_name: str) -> str:
    base, paren, rest = type_name.partition("(")
    short = SHORT_TYPES.get(base, base) + paren + rest
    return short if len(short) <= TYPE_WIDTH else short[: TYPE_WIDTH - 1] + "…"


def _link_detail(link: Link) -> Text:
    near, far = table_name(link.near_relation), table_name(link.far_relation)
    lines = [
        Text(f"on {near}.{near_column} = {far}.{far_column}")
        for near_column, far_column in zip(
            link.near_columns, link.far_columns, strict=True
        )
    ]
    if link.nullable:
        lines.append(Text("nullable → left join", DIM))
    return Text("\n").join(lines)
