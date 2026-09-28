"""Finding catalog items by identifier, loading only what the search needs."""

from __future__ import annotations

from typing import Callable, Sequence

from harlequin.catalog import Catalog, CatalogItem, InteractiveCatalogItem
from harlequin.relations.spelling import split_identifier

OnLoaded = Callable[[CatalogItem, list[CatalogItem]], None]


class CatalogLookup:
    def __init__(self, catalog: Catalog | None, on_loaded: OnLoaded) -> None:
        self._catalog = catalog
        self._on_loaded = on_loaded

    def find(
        self, qualified_identifier: str, database: str | None
    ) -> tuple[CatalogItem, CatalogItem | None] | None:
        """The item and its owner; may query the database, so call from a worker."""
        if self._catalog is None:
            return None
        for database_item in self._catalog.items:
            if database is not None and database_item.label != database:
                continue
            for schema in self._children_of(database_item):
                for relation in self._children_of(schema):
                    if relation.qualified_identifier == qualified_identifier:
                        return relation, schema
                    # only the one relation that can hold the column gets fetched
                    if not qualified_identifier.startswith(
                        f"{relation.qualified_identifier}."
                    ):
                        continue
                    for column in self._children_of(relation):
                        if column.qualified_identifier == qualified_identifier:
                            return column, relation
        return None

    def known_relations(self) -> frozenset[str]:
        """Relations loaded so far; the catalog loads lazily."""
        if self._catalog is None:
            return frozenset()
        relations: set[str] = set()
        stack = list(self._catalog.items)
        while stack:
            item = stack.pop()
            if len(split_identifier(item.query_name)) > 1:
                relations.add(item.qualified_identifier)
            stack.extend(item.children)
        return frozenset(relations)

    def _children_of(self, item: CatalogItem) -> Sequence[CatalogItem]:
        if item.children or not isinstance(item, InteractiveCatalogItem):
            return item.children
        if not item.loaded:
            item.children = list(item.fetch_children())
            item.loaded = True
            self._on_loaded(item, item.children)
        return item.children
