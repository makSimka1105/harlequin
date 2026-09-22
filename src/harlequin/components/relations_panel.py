"""What the catalog item under the cursor is joined to.

The panel answers the question the Data Catalog cannot: which columns line up
with the one you are looking at, and which tables you can reach by joining a few
more. It is a reference, not a generator -- selecting a row inserts a path, never
a `join ... on ...` clause, because a join written by hand is quicker to trust
than one you have to read back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Tree

from harlequin.relations import RelationGraph, RelationLink, Route, split_identifier

if TYPE_CHECKING:
    from textual.widgets._tree import TreeNode

DIRECT_LABEL = "DIRECT"
ROUTED_LABEL = "FURTHER"


class RelationsPanel(Tree[str]):
    """A tree of the foreign keys around one catalog item.

    Node data is the qualified identifier the row stands for, or None for the
    headings and for rows that name nothing insertable. That is what the app
    uses to turn a selection into a path.
    """

    BORDER_TITLE = "Relations"

    # This widget is not in any keymap: it is the fork's own, and vscode's
    # bindings say nothing about it. Vim keys are spelled out here so they work
    # whatever keymap is loaded, alongside the arrow keys Tree already brings.
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "collapse_or_parent", "Collapse", show=False),
        Binding("l", "toggle_node", "Expand", show=False),
        Binding("enter", "insert_path", "Insert Path", show=True),
        Binding("f", "toggle_routes", "Toggle Routes", show=True),
    ]

    class PathRequested(Message):
        """Someone chose a row that names a catalog item worth inserting."""

        def __init__(self, qualified_identifier: str) -> None:
            self.qualified_identifier = qualified_identifier
            super().__init__()

    show_routes = True
    """Whether the FURTHER section is drawn. Toggled by a binding."""

    def __init__(self) -> None:
        super().__init__(label="relations", data=None, id="relations_panel")
        self.show_root = False
        self.guide_depth = 2
        self.graph = RelationGraph(())
        self._subject: str | None = None

    def action_insert_path(self) -> None:
        node = self.cursor_node
        if node is not None and node.data is not None:
            self.post_message(self.PathRequested(node.data))

    def action_collapse_or_parent(self) -> None:
        """Collapse, or step out -- the same `h` the Data Catalog tree uses."""
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None and node.parent is not self.root:
            self.move_cursor_to_line(node.parent.line)

    def action_toggle_routes(self) -> None:
        self.show_routes = not self.show_routes
        self.show(self._subject)

    def update_graph(self, graph: RelationGraph) -> None:
        self.graph = graph
        self.show(self._subject)

    def show(self, qualified_identifier: str | None) -> None:
        """Redraw for the catalog item with the given identifier.

        The identifier may name a column, a relation, or something above them
        (a schema, a database). Only the first two have foreign keys; the rest
        get the quiet line, because saying "no relations" about a schema would
        be true and useless.
        """
        self._subject = qualified_identifier
        self.clear()
        root = self.root

        if not self.graph:
            self._note(root, "no foreign keys")
            return
        if qualified_identifier is None:
            self._note(root, "select a table or a column")
            return

        relation, column = self._as_relation_and_column(qualified_identifier)
        if relation is None:
            self._note(root, "select a table or a column")
            return

        links = (
            self.graph.links_for_column(relation, column)
            if column is not None
            else self.graph.links_for_relation(relation)
        )
        self._add_direct(root, links)
        if self.show_routes:
            self._add_routes(root, self.graph.routes_from(relation))
        if not root.children:
            self._note(root, "nothing references this, and it references nothing")

    def _as_relation_and_column(
        self, qualified_identifier: str
    ) -> tuple[str | None, str | None]:
        """Read an identifier as a relation, and a column within it if it is one.

        A column's identifier is its relation's with one more segment, so the
        relation is found by dropping the last segment -- and whichever of the
        two the graph knows about is the one the identifier names. An identifier
        the graph has never heard of belongs to a table with no keys, or to a
        schema or database, and yields no relation.
        """
        segments = split_identifier(qualified_identifier)
        if self.graph.links_for_relation(qualified_identifier):
            return qualified_identifier, None
        if len(segments) < 2:
            return None, None
        parent = ".".join(f'"{segment}"' for segment in segments[:-1])
        if self.graph.links_for_relation(parent):
            return parent, segments[-1]
        return None, None

    def _note(self, parent: TreeNode[str], message: str) -> None:
        parent.add_leaf(Text(message, style=Style(italic=True, dim=True)), data=None)

    def _add_direct(self, parent: TreeNode[str], links: list[RelationLink]) -> None:
        if not links:
            return
        heading = parent.add(_heading(DIRECT_LABEL), data=None, expand=True)
        for link in links:
            arrow = "→" if link.outgoing else "←"
            near = ", ".join(link.near_columns)
            step = heading.add(
                Text.assemble((f"{arrow} ", _ARROW), near), data=None, expand=True
            )
            step.add_leaf(
                Text.assemble(
                    _short(link.far_relation),
                    (f".{', '.join(link.far_columns)}", _COLUMN),
                ),
                # a single-column key names one column to insert; a composite
                # one names no single thing, so it falls back to the relation
                data=(
                    f'{link.far_relation}."{link.far_columns[0]}"'
                    if len(link.far_columns) == 1
                    else link.far_relation
                ),
            )

    def _add_routes(self, parent: TreeNode[str], routes: list[Route]) -> None:
        if not routes:
            return
        heading = parent.add(_heading(ROUTED_LABEL), data=None, expand=True)
        for route in sorted(routes, key=lambda r: (len(r), r.target)):
            target = heading.add(
                Text.assemble(
                    _short(route.target), (f"  {len(route)} steps", _COUNT)
                ),
                data=route.target,
            )
            for position, step in enumerate(route.steps, start=1):
                target.add_leaf(
                    Text.assemble((f"{position} ", _COUNT), _short(step.far_relation)),
                    data=step.far_relation,
                )


_ARROW = Style(bold=True)
_COLUMN = Style(dim=True)
_COUNT = Style(dim=True)


def _heading(text: str) -> Text:
    return Text(text, style=Style(bold=True, dim=True))


def _short(qualified_identifier: str) -> str:
    """A relation identifier as `schema.table`, without the quoting."""
    return ".".join(split_identifier(qualified_identifier))
