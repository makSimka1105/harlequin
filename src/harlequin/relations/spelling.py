"""How a catalog item is written into a query."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

from harlequin.autocomplete.constants import KEYWORDS

if TYPE_CHECKING:
    from harlequin.catalog import CatalogItem
    from harlequin.relations.scope import BufferScope

UNQUOTED = re.compile(r"^[a-z_][a-z0-9_]*$")
"""An identifier a database reads the same whether or not it is quoted."""

DEFAULT_RESERVED: frozenset[str] = frozenset(KEYWORDS)


def path_for(
    item: CatalogItem,
    owner: CatalogItem | None,
    scope: BufferScope,
    reserved: frozenset[str],
    known_relations: Iterable[str] = (),
) -> str:
    """The text to insert for `item`: its alias path if the query has one, else full."""
    if not _reproducible(item.query_name):
        return item.query_name

    own_segments = split_identifier(item.query_name)
    # adapters qualify a relation's query_name but leave a column's bare
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
    return _spell(split_identifier(owner.query_name) + own_segments, reserved)


def split_identifier(qualified_identifier: str) -> list[str]:
    from harlequin.navigate import split_path

    return [segment for segment, _ in split_path(qualified_identifier)]


def _reproducible(query_name: str) -> bool:
    """Whether re-spelling `query_name` gives it back; false for backtick quoting."""
    from harlequin.navigate import split_path

    return all(
        quoted or UNQUOTED.match(segment) is not None
        for segment, quoted in split_path(query_name)
    )


def _spell(segments: list[str], reserved: frozenset[str]) -> str:
    return ".".join(spell_segment(segment, reserved) for segment in segments)


def spell_segment(segment: str, reserved: frozenset[str]) -> str:
    if UNQUOTED.match(segment) and segment not in reserved:
        return segment
    return '"' + segment.replace('"', '""') + '"'


def spell_relation(qualified_identifier: str, reserved: frozenset[str]) -> str:
    """`schema.table`, the part of a relation's identifier a query writes."""
    return _spell(split_identifier(qualified_identifier)[-2:], reserved)


def table_name(qualified_identifier: str) -> str:
    return split_identifier(qualified_identifier)[-1]
