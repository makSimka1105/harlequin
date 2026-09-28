"""Foreign keys as a graph over relations, walked in both directions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Literal

from harlequin.catalog import ForeignKeyEdge
from harlequin.relations.spelling import split_identifier

DEFAULT_MAX_STEPS = 4

Direction = Literal["out", "in"]
DIRECTIONS: tuple[Direction, ...] = ("out", "in")


@dataclass(frozen=True)
class Link:
    """One foreign key seen from one of its ends."""

    edge: ForeignKeyEdge
    direction: Direction

    @property
    def near_relation(self) -> str:
        return self.edge.from_relation if self._out else self.edge.to_relation

    @property
    def far_relation(self) -> str:
        return self.edge.to_relation if self._out else self.edge.from_relation

    @property
    def near_columns(self) -> tuple[str, ...]:
        return self.edge.from_columns if self._out else self.edge.to_columns

    @property
    def far_columns(self) -> tuple[str, ...]:
        return self.edge.to_columns if self._out else self.edge.from_columns

    @property
    def cardinality(self) -> str:
        return "N:1" if self._out else "1:N"

    @property
    def nullable(self) -> bool:
        return self._out and self.edge.nullable

    @property
    def _out(self) -> bool:
        return self.direction == "out"


@dataclass(frozen=True)
class Route:
    steps: tuple[Link, ...]

    @property
    def source(self) -> str:
        return self.steps[0].near_relation

    @property
    def target(self) -> str:
        return self.steps[-1].far_relation

    def __len__(self) -> int:
        return len(self.steps)


class RelationGraph:
    def __init__(self, edges: Iterable[ForeignKeyEdge]) -> None:
        self._links: dict[str, list[Link]] = {}
        self._databases: set[str | None] = set()
        for edge in edges:
            self._databases.add(edge.database)
            for direction in DIRECTIONS:
                link = Link(edge=edge, direction=direction)
                self._links.setdefault(link.near_relation, []).append(link)
        for links in self._links.values():
            links.sort(key=lambda link: (link.far_relation, link.near_columns))

    def __bool__(self) -> bool:
        return bool(self._links)

    def covers(self, database: str | None) -> bool:
        return None in self._databases or database in self._databases

    @property
    def relations(self) -> list[str]:
        return sorted(self._links)

    def links_for(self, relation: str) -> list[Link]:
        return list(self._links.get(relation, ()))

    def has_parallel(self, link: Link) -> bool:
        """Whether another key joins the same two relations the same way."""
        return any(
            other.edge != link.edge
            and other.far_relation == link.far_relation
            and other.direction == link.direction
            for other in self._links.get(link.near_relation, ())
        )

    def relation_of(self, identifier: str) -> tuple[str, str | None] | None:
        """The relation an identifier names, and the column if it names one."""
        if identifier in self._links:
            return identifier, None
        segments = split_identifier(identifier)
        if len(segments) < 2:
            return None
        parent = ".".join(f'"{segment}"' for segment in segments[:-1])
        if parent in self._links:
            return parent, segments[-1]
        return None

    def routes_from(
        self, relation: str, max_steps: int = DEFAULT_MAX_STEPS
    ) -> list[Route]:
        """Shortest routes to relations two or more steps away."""
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
