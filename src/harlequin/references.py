"""What the current buffer calls the things in the catalog.

Inserting a name is only useful if the query can use it: a table written under
an alias has to be reached through that alias, because naming it in full is an
error once it is aliased. So every insertion asks this module what the buffer
already says about the item's table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from harlequin.autocomplete.constants import KEYWORDS

if TYPE_CHECKING:
    from tree_sitter import Node

    from harlequin.catalog import CatalogItem

RELATION_QUERY = "(relation) @relation"
"""Every table named in a FROM or JOIN, with whatever follows it as an alias."""

CTE_QUERY = "(cte (identifier) @name) @cte"
"""The names a WITH clause introduces, which no catalog item ever matches."""


@dataclass(frozen=True)
class RelationRef:
    """One table as the buffer writes it."""

    name: str
    """The relation as written, e.g. "sales.customer". Not normalized."""

    alias: str | None
    is_cte: bool


@dataclass(frozen=True)
class BufferScope:
    """The relations a buffer names, in the order they first appear."""

    relations: tuple[RelationRef, ...] = field(default=())

    def alias_for(self, qualified_identifier: str) -> str | None:
        """The alias under which `qualified_identifier` is available, if one is.

        A written reference matches an item when its segments equal the item's
        last segments: `sales.customer` reaches
        `"retail_training"."sales"."customer"`. If more than one reference
        matches -- two bare `customer`s from different schemas -- there is no
        answer, and the caller falls back to the full path. Guessing here would
        produce a query that is wrong rather than merely verbose.
        """
        from harlequin.navigate import split_path

        target = [segment.casefold() for segment, _ in split_path(qualified_identifier)]
        found: list[str] = []
        for relation in self.relations:
            if relation.alias is None or relation.is_cte:
                continue
            written = [segment.casefold() for segment, _ in split_path(relation.name)]
            if written and written == target[-len(written) :]:
                found.append(relation.alias)
        return found[0] if len(found) == 1 else None


def read_scope(text: str) -> BufferScope:
    """Read every relation the buffer names, with its alias where it has one."""
    if not text.strip():
        return BufferScope()

    # deferred: every adapter imports this package, and only an insertion into
    # the Query Editor ever parses SQL with it.
    from harlequin.statements import captures

    cte_names = {
        node.text.decode("utf-8").casefold()
        for node in captures(text, CTE_QUERY).get("name", [])
        if node.text is not None
    }

    relations: list[RelationRef] = []
    for node in sorted(
        captures(text, RELATION_QUERY).get("relation", []),
        key=lambda found: found.start_byte,
    ):
        name, alias = _name_and_alias(node)
        if not name:
            continue
        relations.append(
            RelationRef(name=name, alias=alias, is_cte=name.casefold() in cte_names)
        )
    return BufferScope(relations=tuple(relations))


def _name_and_alias(relation: Node) -> tuple[str, str | None]:
    """The table and its alias, read off the relation node's own children.

    Not from paired captures: `captures()` returns one list per capture name,
    and their orders do not line up, so the third table would be handed the
    second alias.
    """
    name = ""
    alias: str | None = None
    for child in relation.children:
        if child.text is None:
            continue
        if child.type == "object_reference":
            name = child.text.decode("utf-8")
        elif child.type == "identifier":
            alias = child.text.decode("utf-8")
    return name, alias


UNQUOTED = re.compile(r"^[a-z_][a-z0-9_]*$")
"""An identifier a database reads the same whether or not it is quoted."""

DEFAULT_RESERVED: frozenset[str] = frozenset(KEYWORDS)
"""The words core knows are reserved, before an adapter says what it reserves."""


def path_for(
    item: "CatalogItem",
    owner: "CatalogItem | None",
    scope: BufferScope,
    reserved: frozenset[str],
) -> str:
    """The text to insert for `item`, usable in the query as it stands.

    An adapter spells `query_name` two ways: a relation's is already qualified
    by its schema, a column's is the bare column. So a single-segment name is
    the one that needs its owner in front of it, and that is what tells the two
    apart without core knowing which adapter it is talking to.
    """
    own_segments = _segments(item.query_name)
    if len(own_segments) > 1:
        alias = scope.alias_for(item.qualified_identifier)
        return alias if alias else _spell(own_segments, reserved)

    if owner is None:
        return _spell(own_segments, reserved)

    alias = scope.alias_for(owner.qualified_identifier)
    if alias:
        return f"{alias}.{_spell(own_segments, reserved)}"
    return _spell(_segments(owner.query_name) + own_segments, reserved)


def _segments(query_name: str) -> list[str]:
    from harlequin.navigate import split_path

    return [segment for segment, _ in split_path(query_name)]


def _spell(segments: list[str], reserved: frozenset[str]) -> str:
    return ".".join(_spell_segment(segment, reserved) for segment in segments)


def _spell_segment(segment: str, reserved: frozenset[str]) -> str:
    if UNQUOTED.match(segment) and segment not in reserved:
        return segment
    return '"' + segment.replace('"', '""') + '"'
