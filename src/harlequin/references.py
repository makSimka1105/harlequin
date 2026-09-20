"""What the current buffer calls the things in the catalog.

Inserting a name is only useful if the query can use it: a table written under
an alias has to be reached through that alias, because naming it in full is an
error once it is aliased. So every insertion asks this module what the buffer
already says about the item's table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

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

    def alias_for(
        self, qualified_identifier: str, known_relations: Iterable[str] = ()
    ) -> str | None:
        """The alias under which `qualified_identifier` is available, if one is.

        A written reference matches an item when its segments equal the item's
        last segments: `sales.customer` reaches
        `"retail_training"."sales"."customer"`. A segment the buffer wrote in
        quotes compares case-sensitively against the catalog's spelling; an
        unquoted one is casefolded first, since that is how the database itself
        would read it.

        There is no answer, and the caller falls back to the full path, in two
        cases where guessing would produce a query that is wrong rather than
        merely verbose: more than one written reference matches this item (two
        bare `customer`s from different schemas), or the one reference that
        matches is itself ambiguous against `known_relations` -- a bare
        `customer` also suffix-matches both `sales.customer` and
        `archive.customer`, so it cannot be trusted to name either.

        `known_relations` should be every relation's `qualified_identifier`,
        but the Data Catalog loads lazily: a schema branch nobody has expanded
        contributes nothing here. This check is best-effort against whatever
        the catalog happens to hold already, not a guarantee against every
        relation that exists.
        """
        from harlequin.navigate import split_path

        target = split_path(qualified_identifier)
        catalog_paths = [split_path(identifier) for identifier in known_relations]

        found: list[str] = []
        for relation in self.relations:
            if relation.alias is None or relation.is_cte:
                continue
            written = split_path(relation.name)
            if not _suffix_matches(written, target):
                continue
            if sum(1 for path in catalog_paths if _suffix_matches(written, path)) > 1:
                continue
            found.append(relation.alias)
        return found[0] if len(found) == 1 else None


def _suffix_matches(
    written: list[tuple[str, bool]], catalog_path: list[tuple[str, bool]]
) -> bool:
    """Whether `written` names the tail of `catalog_path`, segment by segment.

    Only `written`'s own quoting decides how a pair compares -- the catalog's
    spelling is presumed canonical, so its own quoted flag is not consulted.
    """
    if not written or len(written) > len(catalog_path):
        return False
    offset = len(catalog_path) - len(written)
    return all(
        w == c if w_quoted else w.casefold() == c.casefold()
        for (w, w_quoted), (c, _) in zip(written, catalog_path[offset:], strict=True)
    )


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
    known_relations: Iterable[str] = (),
) -> str:
    """The text to insert for `item`, usable in the query as it stands.

    An adapter spells `query_name` two ways: a relation's is already qualified
    by its schema, a column's is the bare column. So a single-segment name is
    the one that needs its owner in front of it, and that is what tells the two
    apart without core knowing which adapter it is talking to.

    That trick, and the quoting this then does, both assume the adapter quotes
    with `"`, the way postgres and duckdb do. An adapter that quotes some other
    way -- bigquery spells a column `` `col` `` -- would have core re-spell
    something it does not understand, guessing wrong rather than merely
    verbosely. `item.query_name` is returned unchanged -- it is the adapter's
    own, already-correct spelling -- whenever re-spelling its segments would
    not reproduce it.

    `known_relations` narrows an alias match against every other relation the
    caller knows of; see `BufferScope.alias_for` for what that guards against
    and its lazy-catalog limitation.
    """
    if not _reproducible(item.query_name):
        return item.query_name

    own_segments = _segments(item.query_name)
    if len(own_segments) > 1:
        alias = scope.alias_for(item.qualified_identifier, known_relations)
        return alias if alias else _spell(own_segments, reserved)

    if owner is None:
        return _spell(own_segments, reserved)

    if not _reproducible(owner.query_name):
        return item.query_name

    alias = scope.alias_for(owner.qualified_identifier, known_relations)
    if alias:
        return f"{alias}.{_spell(own_segments, reserved)}"
    return _spell(_segments(owner.query_name) + own_segments, reserved)


def _segments(query_name: str) -> list[str]:
    from harlequin.navigate import split_path

    return [segment for segment, _ in split_path(query_name)]


def _reproducible(query_name: str) -> bool:
    """Whether `_spell_segment` could plausibly have written `query_name`.

    A segment `split_path` reports as unquoted must actually be a safe bare
    identifier, the one shape `_spell_segment` ever leaves unquoted. An
    adapter that quotes with something other than `"` fails this: its
    segments come back unquoted -- nothing here recognizes its quote
    character -- yet are not valid bare SQL, e.g. bigquery's `` `t` ``.
    """
    from harlequin.navigate import split_path

    return all(
        quoted or UNQUOTED.match(segment) is not None
        for segment, quoted in split_path(query_name)
    )


def _spell(segments: list[str], reserved: frozenset[str]) -> str:
    return ".".join(_spell_segment(segment, reserved) for segment in segments)


def _spell_segment(segment: str, reserved: frozenset[str]) -> str:
    if UNQUOTED.match(segment) and segment not in reserved:
        return segment
    return '"' + segment.replace('"', '""') + '"'
