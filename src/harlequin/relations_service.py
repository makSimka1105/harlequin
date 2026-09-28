"""Everything the app asks about relations, behind one object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from harlequin.catalog import Catalog, CatalogItem
from harlequin.catalog_lookup import CatalogLookup, OnLoaded
from harlequin.relations.candidates import join_candidates
from harlequin.relations.graph import RelationGraph, Route
from harlequin.relations.joins import AliasSlot, JoinPlan, JoinRefusal, plan_joins
from harlequin.relations.pointer import pointer_at
from harlequin.relations.schema import SchemaIndex
from harlequin.relations.scope import BufferScope, names, read_scope
from harlequin.relations.spelling import (
    DEFAULT_RESERVED,
    path_for,
    split_identifier,
    table_name,
)
from harlequin.statements import StatementSpan


@dataclass(frozen=True)
class Edit:
    offset: int | None
    """Buffer offset to insert at; None inserts at the cursor."""
    text: str


@dataclass(frozen=True)
class Focus:
    relation: str
    column: str | None = None


@dataclass(frozen=True)
class JoinCandidate:
    route: Route
    source: str
    preview: str
    aliases: tuple[AliasSlot, ...] = ()


class RelationsService:
    def __init__(self, on_loaded: OnLoaded) -> None:
        self._on_loaded = on_loaded
        self.graph = RelationGraph(())
        self.schema = SchemaIndex(())
        self.lookup = CatalogLookup(None, on_loaded)
        self.reserved: frozenset[str] = DEFAULT_RESERVED

    def update_catalog(self, catalog: Catalog | None) -> None:
        self.lookup = CatalogLookup(catalog, self._on_loaded)

    def path_for_item(
        self, item: CatalogItem, owner: CatalogItem | None, statement: str
    ) -> str:
        return path_for(
            item=item,
            owner=owner,
            scope=read_scope(statement),
            reserved=self.reserved,
            known_relations=self.lookup.known_relations(),
        )

    def path_text(
        self, identifier: str, database: str | None, statement: str
    ) -> str | None:
        found = self.lookup.find(identifier, database)
        if found is None:
            return None
        item, owner = found
        return self.path_for_item(item, owner, statement)

    def join_edit(
        self,
        route: Route,
        statement: StatementSpan | None,
        aliases: Sequence[str] = (),
    ) -> Edit | JoinRefusal:
        plan = plan_joins(
            route,
            _scope(statement),
            self.reserved,
            self.lookup.known_relations(),
            self.graph,
            aliases,
        )
        if isinstance(plan, JoinRefusal):
            return plan
        if statement is None:
            return Edit(offset=None, text=plan.text)
        if plan.anchor is None:
            end = statement.start + len(statement.text)
            return Edit(offset=end, text="\n" + plan.text)
        return Edit(offset=statement.start + plan.anchor, text=plan.text)

    def join_candidates(self, statement: StatementSpan | None) -> list[JoinCandidate]:
        scope = _scope(statement)
        known = self.lookup.known_relations()
        candidates: list[JoinCandidate] = []
        for route in join_candidates(scope, self.graph, known):
            plan = plan_joins(route, scope, self.reserved, known, self.graph)
            source = scope.reference_for(route.source, known) or table_name(
                route.source
            )
            candidates.append(
                JoinCandidate(
                    route=route,
                    source=source,
                    preview=_preview(plan),
                    aliases=plan.aliases if isinstance(plan, JoinPlan) else (),
                )
            )
        return candidates

    def focus_on(self, identifier: str) -> Focus | None:
        """The table or column a catalog identifier names, if the schema knows it."""
        relations = self._relations()
        if identifier in relations:
            return Focus(identifier)
        segments = split_identifier(identifier)
        parent = ".".join(f'"{segment}"' for segment in segments[:-1])
        if len(segments) > 1 and parent in relations:
            return Focus(parent, self._column_name(parent, f'"{segments[-1]}"'))
        return None

    def focus_at(self, statement: StatementSpan | None, offset: int) -> Focus | None:
        """What the name under the editor cursor refers to, through the aliases."""
        if statement is None:
            return None
        pointer = pointer_at(statement.text, offset - statement.start)
        if pointer is None:
            return None
        scope = read_scope(statement.text)
        if pointer.table:
            relation = self._relation_named(pointer.name, scope)
            return Focus(relation) if relation is not None else None
        if pointer.qualifier is not None:
            relation = self._relation_named(pointer.qualifier, scope)
            if relation is None:
                return None
            return Focus(relation, self._column_name(relation, pointer.name))
        owners = {
            relation
            for ref in scope.relations
            if ref.top_level and not ref.is_cte
            if (relation := self._relation_named(ref.name, scope)) is not None
            and self.schema.column(relation, pointer.name) is not None
        }
        if len(owners) == 1:
            [relation] = owners
            return Focus(relation, self._column_name(relation, pointer.name))
        relation = self._relation_named(pointer.name, scope)
        return Focus(relation) if relation is not None and not owners else None

    def _relations(self) -> set[str]:
        return {*self.schema.relations, *self.graph.relations}

    def _relation_named(self, written: str, scope: BufferScope) -> str | None:
        aliased_names = [
            ref.name
            for ref in scope.relations
            if not ref.is_cte
            and ref.alias is not None
            and ref.alias.casefold() == written.casefold()
        ]
        if aliased_names:
            written = aliased_names[0]
        matching_relations = [
            relation for relation in self._relations() if names(written, relation)
        ]
        return matching_relations[0] if len(matching_relations) == 1 else None

    def _column_name(self, relation: str, written: str) -> str | None:
        """The column's real name; the written one when the schema lists none."""
        if not self.schema.columns_of(relation):
            return split_identifier(written)[0]
        column = self.schema.column(relation, written)
        return column.name if column is not None else None


def _scope(statement: StatementSpan | None) -> BufferScope:
    return read_scope(statement.text) if statement is not None else BufferScope()


def _preview(plan: JoinPlan | JoinRefusal) -> str:
    if isinstance(plan, JoinRefusal):
        return plan.reason
    return "\n".join(line.strip() for line in plan.text.splitlines() if line.strip())
