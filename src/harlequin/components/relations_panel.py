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
from textual.widgets import Tree

from harlequin.relations import RelationGraph, RelationLink, Route, split_identifier

if TYPE_CHECKING:
    from textual.widgets._tree import TreeNode

DIRECT_LABEL = "DIRECT"
ROUTED_LABEL = "FURTHER"


class RelationsPanel(Tree[str], inherit_bindings=False):
    """A tree of the foreign keys around one catalog item.

    Node data is the qualified identifier the row stands for, or None for the
    headings and for rows that name nothing insertable. That is what the app
    uses to turn a selection into a path.
    """

    BORDER_TITLE = "Relations"

    show_routes = True
    """Whether the FURTHER section is drawn. Toggled by a binding."""

    def __init__(self) -> None:
        super().__init__(label="relations", data=None, id="relations_panel")
        self.show_root = False
        self.guide_depth = 2
        self.graph = RelationGraph(())
        self._subject: str | None = None

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
                data=link.far_relation,
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
