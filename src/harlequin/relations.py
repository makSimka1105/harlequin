"""What a catalog item is joined to, one step away and further.

Foreign keys form a graph over relations, and the question the Relations panel
answers -- "what can I join this to?" -- is a walk over it. The walk ignores the
direction of a key: a table is just as joinable to the one that references it as
to the one it references. Each step still remembers which way it was crossed, so
the panel can show `->` and `<-` honestly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Sequence

from harlequin.catalog import ForeignKeyEdge

DEFAULT_MAX_STEPS = 4
"""How far the search walks before giving up on a relation.

Not a performance limit -- the graph is tiny -- but a usefulness one: nobody
writes a join across seven tables from a hint in a side panel.
"""


@dataclass(frozen=True)
class RelationLink:
    """One foreign key, seen from one of its two ends."""

    edge: ForeignKeyEdge
    outgoing: bool
    """True when the near end is the referencing side, i.e. this end points out."""

    @property
    def near_relation(self) -> str:
        return self.edge.from_relation if self.outgoing else self.edge.to_relation

    @property
    def far_relation(self) -> str:
        return self.edge.to_relation if self.outgoing else self.edge.from_relation

    @property
    def near_columns(self) -> tuple[str, ...]:
        return self.edge.from_columns if self.outgoing else self.edge.to_columns

    @property
    def far_columns(self) -> tuple[str, ...]:
        return self.edge.to_columns if self.outgoing else self.edge.from_columns


@dataclass(frozen=True)
class Route:
    """A shortest way from one relation to another, as the steps taken."""

    steps: tuple[RelationLink, ...]

    @property
    def target(self) -> str:
        return self.steps[-1].far_relation

    def __len__(self) -> int:
        return len(self.steps)


class RelationGraph:
    """The foreign keys of a database, indexed for the two questions asked of them."""

    def __init__(self, edges: Iterable[ForeignKeyEdge]) -> None:
        self._links: dict[str, list[RelationLink]] = {}
        for edge in edges:
            self._add(RelationLink(edge=edge, outgoing=True))
            self._add(RelationLink(edge=edge, outgoing=False))

    def _add(self, link: RelationLink) -> None:
        self._links.setdefault(link.near_relation, []).append(link)

    def __bool__(self) -> bool:
        return bool(self._links)

    def links_for_relation(self, relation: str) -> list[RelationLink]:
        """Every key touching this relation, in a stable order."""
        return list(self._links.get(relation, ()))

    def links_for_column(self, relation: str, column: str) -> list[RelationLink]:
        """Every key that this particular column takes part in."""
        return [
            link
            for link in self._links.get(relation, ())
            if column in link.near_columns
        ]

    def routes_from(
        self, relation: str, max_steps: int = DEFAULT_MAX_STEPS
    ) -> list[Route]:
        """Relations reachable in more than one step, each by one shortest route.

        Breadth first, so the first route found to a relation is a shortest one;
        every relation is reported once, and the start is never a destination.
        Direct neighbours are left out: the panel lists those separately, with
        their columns, and repeating them here would say nothing new.
        """
        seen = {relation}
        seen.update(link.far_relation for link in self._links.get(relation, ()))
        queue: deque[Route] = deque(
            Route(steps=(link,)) for link in self._links.get(relation, ())
        )
        routes: list[Route] = []
        while queue:
            route = queue.popleft()
            if len(route) >= max_steps:
                continue
            for link in self._links.get(route.target, ()):
                if link.far_relation in seen:
                    continue
                seen.add(link.far_relation)
                longer = Route(steps=(*route.steps, link))
                routes.append(longer)
                queue.append(longer)
        return routes


def split_identifier(qualified_identifier: str) -> Sequence[str]:
    """The segments of a catalog identifier, quotes stripped."""
    from harlequin.navigate import split_path

    return [segment for segment, _ in split_path(qualified_identifier)]
