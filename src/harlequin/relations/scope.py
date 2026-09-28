"""What the statement under the cursor calls the relations it uses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from tree_sitter import Node

RELATION_QUERY = "(relation) @relation"
JOIN_QUERY = "(join) @join"
CTE_QUERY = "(cte (identifier) @name) @cte"
NESTED = frozenset({"subquery", "cte"})


@dataclass(frozen=True)
class RelationRef:
    name: str
    """As written, e.g. "sales.customer"; not normalized."""
    alias: str | None
    is_cte: bool
    top_level: bool = True

    @property
    def reference(self) -> str:
        return self.alias or self.name


@dataclass(frozen=True)
class BufferScope:
    relations: tuple[RelationRef, ...] = field(default=())
    anchor: int | None = None
    """Character offset right after the last top-level join or from relation."""
    indent: str = ""

    def alias_for(
        self, qualified_identifier: str, known_relations: Iterable[str] = ()
    ) -> str | None:
        """The one alias the buffer gives this relation; None when ambiguous."""
        aliases = [
            ref.alias
            for _, ref in self._matches(qualified_identifier, known_relations)
            if ref.alias is not None
        ]
        return aliases[0] if len(aliases) == 1 else None

    def reference_for(
        self, qualified_identifier: str, known_relations: Iterable[str] = ()
    ) -> str | None:
        position = self.position_of(qualified_identifier, known_relations)
        return None if position is None else self.relations[position].reference

    def position_of(
        self, qualified_identifier: str, known_relations: Iterable[str] = ()
    ) -> int | None:
        """Where the top-level query first names this relation."""
        return next(
            (
                index
                for index, ref in self._matches(qualified_identifier, known_relations)
                if ref.top_level
            ),
            None,
        )

    def taken_names(self) -> set[str]:
        from harlequin.navigate import split_path

        return {
            split_path(ref.reference)[-1][0].casefold()
            for ref in self.relations
            if ref.top_level
        }

    def _matches(
        self, qualified_identifier: str, known_relations: Iterable[str]
    ) -> list[tuple[int, RelationRef]]:
        from harlequin.navigate import split_path

        target = split_path(qualified_identifier)
        catalog_paths = [split_path(identifier) for identifier in known_relations]
        matches: list[tuple[int, RelationRef]] = []
        for index, ref in enumerate(self.relations):
            if ref.is_cte:
                continue
            written = split_path(ref.name)
            if not _suffix_matches(written, target):
                continue
            if sum(1 for path in catalog_paths if _suffix_matches(written, path)) > 1:
                continue
            matches.append((index, ref))
        return matches


def names(written: str, qualified_identifier: str) -> bool:
    """Whether `written` spells the tail of `qualified_identifier`."""
    from harlequin.navigate import split_path

    return _suffix_matches(split_path(written), split_path(qualified_identifier))


def _suffix_matches(
    written: list[tuple[str, bool]], catalog_path: list[tuple[str, bool]]
) -> bool:
    """Whether `written` names the tail of `catalog_path`."""
    if not written or len(written) > len(catalog_path):
        return False
    offset = len(catalog_path) - len(written)
    # a quoted segment compares exactly, an unquoted one casefolded
    return all(
        w == c if w_quoted else w.casefold() == c.casefold()
        for (w, w_quoted), (c, _) in zip(written, catalog_path[offset:], strict=True)
    )


def read_scope(text: str) -> BufferScope:
    if not text.strip():
        return BufferScope()

    # deferred: adapters import this package, and only the editor parses SQL
    from harlequin.statements import captures

    cte_names = {
        node.text.decode("utf-8").casefold()
        for node in captures(text, CTE_QUERY).get("name", [])
        if node.text is not None
    }

    relations: list[RelationRef] = []
    clause_ends: list[Node] = []
    for node in sorted(
        captures(text, RELATION_QUERY).get("relation", []),
        key=lambda found: found.start_byte,
    ):
        top_level = _is_top_level(node)
        if top_level:
            clause_ends.append(node)
        name, alias = _name_and_alias(node)
        if name:
            relations.append(
                RelationRef(
                    name=name,
                    alias=alias,
                    is_cte=name.casefold() in cte_names,
                    top_level=top_level,
                )
            )
    clause_ends.extend(
        node
        for node in captures(text, JOIN_QUERY).get("join", [])
        if _is_top_level(node)
    )
    if not clause_ends:
        return BufferScope(relations=tuple(relations))

    # tree-sitter counts bytes; the editor counts characters
    last = max(clause_ends, key=lambda node: node.end_byte)
    encoded = text.encode("utf-8")
    anchor = len(encoded[: last.end_byte].decode("utf-8"))
    start = len(encoded[: last.start_byte].decode("utf-8"))
    line = text[text.rfind("\n", 0, start) + 1 :]
    indent = line[: len(line) - len(line.lstrip(" \t"))]
    return BufferScope(relations=tuple(relations), anchor=anchor, indent=indent)


def _is_top_level(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in NESTED:
            return False
        parent = parent.parent
    return True


def _name_and_alias(relation: Node) -> tuple[str, str | None]:
    # read off the node's children: paired captures come back out of order
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
