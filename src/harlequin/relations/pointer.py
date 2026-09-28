"""The table or column name the editor cursor sits on, as written."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node

IDENTIFIER_QUERY = "(identifier) @identifier"


@dataclass(frozen=True)
class Pointer:
    qualifier: str | None
    name: str
    table: bool = False


def pointer_at(text: str, offset: int) -> Pointer | None:
    if not text.strip():
        return None

    from harlequin.statements import captures

    # tree-sitter counts bytes; a cursor right after a word still means that word
    cursor_byte = len(text[:offset].encode("utf-8"))
    identifiers_under_cursor = [
        node
        for node in captures(text, IDENTIFIER_QUERY).get("identifier", [])
        if node.start_byte <= cursor_byte <= node.end_byte
    ]
    if not identifiers_under_cursor:
        return None
    return _pointer_for(
        min(
            identifiers_under_cursor,
            key=lambda node: abs(node.start_byte - cursor_byte),
        )
    )


def _pointer_for(identifier: Node) -> Pointer | None:
    parent = identifier.parent
    if parent is None:
        return None
    if parent.type == "object_reference":
        return Pointer(qualifier=None, name=_text(parent), table=True)
    if parent.type == "relation":
        return Pointer(qualifier=None, name=_text(identifier), table=True)
    if parent.type == "field":
        qualifier = next(
            (child for child in parent.children if child.type == "object_reference"),
            None,
        )
        return Pointer(
            qualifier=_text(qualifier) if qualifier is not None else None,
            name=_text(identifier),
        )
    return None


def _text(node: Node) -> str:
    return node.text.decode("utf-8") if node.text is not None else ""
