"""What the statement under the cursor can be joined to."""

from __future__ import annotations

from typing import Iterable

from harlequin.relations.graph import RelationGraph, Route
from harlequin.relations.scope import BufferScope


def join_candidates(
    scope: BufferScope, graph: RelationGraph, known_relations: Iterable[str] = ()
) -> list[Route]:
    """Every direct key first, then the shortest route to each other table."""
    known = list(known_relations)
    present = sorted(
        (position, relation)
        for relation in graph.relations
        if (position := scope.position_of(relation, known)) is not None
    )
    present_ids = {relation for _, relation in present}

    direct: list[Route] = []
    routed: dict[str, Route] = {}
    for _, relation in present:
        for link in graph.links_for(relation):
            if (
                link.far_relation not in present_ids
                or link.far_relation == relation
                or graph.has_parallel(link)
            ):
                direct.append(Route((link,)))
        for route in graph.routes_from(relation):
            best = routed.get(route.target)
            if route.target not in present_ids and (
                best is None or len(route) < len(best)
            ):
                routed[route.target] = route

    direct_targets = {route.target for route in direct}
    further = [
        route for target, route in routed.items() if target not in direct_targets
    ]
    return direct + sorted(further, key=lambda route: (len(route), route.target))
