"""The catalog, cut down to what matched a search.

A separate tree rather than a filter over the real one: the catalog loads
lazily, so filtering it in place would either hide branches whose children have
never been fetched, or force fetching all of them. Searching asks the database
directly, gets back matches from every level at once, and this tree rebuilds the
few branches needed to show them -- while the real tree stays mounted, with its
expansions and cursor intact, ready to come back the moment the filter clears.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from harlequin.catalog import CatalogItem, CatalogSearchResult
from harlequin.components.data_catalog.tree import HarlequinTree

if TYPE_CHECKING:
    from textual.widgets._tree import TreeNode


class FilteredTree(HarlequinTree[CatalogItem], inherit_bindings=False):
    """Search results, arranged back into the shape the catalog had."""

    BORDER_TITLE = "Data Catalog"

    def __init__(self) -> None:
        super().__init__(
            label="filtered",
            data=CatalogItem(
                qualified_identifier="__filtered__",
                query_name="",
                label="filtered",
                type_label="",
            ),
            id="filtered_tree",
        )
        self.show_root = False
        self.guide_depth = 3

    def show_results(self, results: Iterable[CatalogSearchResult]) -> None:
        """Rebuild from a flat list of matches, restoring their ancestry.

        A match arrives with the labels of everything above it, so the same
        ancestor reached by several matches must become one branch, not one per
        match. Ancestors exist only to hold the matches, which is why they carry
        no catalog item: submitting one would insert a name the search never
        matched.
        """
        self.clear()
        branches: dict[tuple[str, ...], TreeNode[CatalogItem]] = {}
        for result in results:
            parent = self.root
            for depth in range(len(result.parents)):
                path = result.parents[: depth + 1]
                branch = branches.get(path)
                if branch is None:
                    branch = parent.add(path[-1], data=None, expand=True)
                    branches[path] = branch
                parent = branch
            label = self._build_item_label(result.item.label, result.item.type_label)
            if result.item.children or not getattr(result.item, "loaded", True):
                node = parent.add(label, data=result.item, expand=False)
                branches[(*result.parents, result.item.label)] = node
            else:
                parent.add_leaf(label, data=result.item)
