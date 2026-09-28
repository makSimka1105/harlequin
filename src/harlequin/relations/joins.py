"""Join clauses for a route, written into the statement under the cursor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from harlequin.relations.graph import Link, RelationGraph, Route
from harlequin.relations.scope import BufferScope
from harlequin.relations.spelling import (
    UNQUOTED,
    spell_relation,
    spell_segment,
    table_name,
)


@dataclass(frozen=True)
class AliasSlot:
    relation: str
    alias: str


@dataclass(frozen=True)
class JoinPlan:
    anchor: int | None
    """Statement offset to insert at; None inserts at the cursor."""
    text: str
    aliases: tuple[AliasSlot, ...] = ()
    """The aliases the plan introduces, in the order they appear."""


@dataclass(frozen=True)
class JoinRefusal:
    reason: str
    slot: int | None = None
    """The chosen alias that caused the refusal, by its index in `aliases`."""


class _UnusableAlias(Exception):
    def __init__(self, refusal: JoinRefusal) -> None:
        self.refusal = refusal


def plan_joins(
    route: Route,
    scope: BufferScope,
    reserved: frozenset[str],
    known_relations: Iterable[str] = (),
    graph: RelationGraph | None = None,
    aliases: Sequence[str] = (),
) -> JoinPlan | JoinRefusal:
    """Plan the joins for `route`; blank or missing `aliases` are generated."""
    try:
        return _plan(route, scope, reserved, known_relations, graph, aliases)
    except _UnusableAlias as unusable:
        return unusable.refusal


def _alias_problem(alias: str, taken: set[str], reserved: frozenset[str]) -> str | None:
    if not UNQUOTED.match(alias):
        return f"{alias} — не имя"
    if alias in reserved:
        return f"{alias} — ключевое слово"
    if alias in taken:
        return f"{alias} уже занят"
    return None


def _plan(
    route: Route,
    scope: BufferScope,
    reserved: frozenset[str],
    known_relations: Iterable[str],
    graph: RelationGraph | None,
    chosen: Sequence[str],
) -> JoinPlan | JoinRefusal:
    known = list(known_relations)
    taken = scope.taken_names()
    lines: list[str] = []
    slots: list[AliasSlot] = []

    def claim(relation: str) -> str:
        index = len(slots)
        wanted = chosen[index] if index < len(chosen) else ""
        if wanted:
            problem = _alias_problem(wanted, taken, reserved)
            if problem is not None:
                raise _UnusableAlias(JoinRefusal(problem, slot=index))
            taken.add(wanted)
        alias = wanted or new_alias(relation, taken, reserved)
        slots.append(AliasSlot(relation, alias))
        return alias

    current = scope.reference_for(route.source, known)
    if current is None:
        if scope.anchor is not None:
            return JoinRefusal(f"{table_name(route.source)} нет в запросе")
        current = claim(route.source)
        lines.append(f"from {spell_relation(route.source, reserved)} {current}")

    joined = False
    for link in route.steps:
        # with two keys between the tables the present join may use the other one
        rejoin = link.far_relation == link.near_relation or (
            graph is not None and graph.has_parallel(link)
        )
        present = None if rejoin else scope.reference_for(link.far_relation, known)
        if present is not None:
            current = present
            continue
        alias = claim(link.far_relation)
        lines.append(_join_line(link, alias, current, reserved))
        current = alias
        joined = True

    if not joined:
        return JoinRefusal(f"{table_name(route.target)} уже в запросе")
    if scope.anchor is None:
        return JoinPlan(anchor=None, text="\n".join(lines), aliases=tuple(slots))
    return JoinPlan(
        anchor=scope.anchor,
        text="".join(f"\n{scope.indent}{line}" for line in lines),
        aliases=tuple(slots),
    )


def new_alias(
    qualified_identifier: str, taken: set[str], reserved: frozenset[str]
) -> str:
    name = table_name(qualified_identifier).casefold()
    words = [word for word in name.split("_") if word]
    base = "".join(word[0] for word in words) if len(words) > 1 else name[:1]
    if not UNQUOTED.match(base):
        base = "t"
    alias, number = base, 1
    while alias in taken or alias in reserved:
        number += 1
        alias = f"{base}{number}"
    taken.add(alias)
    return alias


def _join_line(link: Link, alias: str, known: str, reserved: frozenset[str]) -> str:
    kind = "left join" if link.nullable else "join"
    condition = " and ".join(
        f"{alias}.{spell_segment(far, reserved)} = "
        f"{known}.{spell_segment(near, reserved)}"
        for near, far in zip(link.near_columns, link.far_columns, strict=True)
    )
    relation = spell_relation(link.far_relation, reserved)
    return f"{kind} {relation} {alias} on {condition}"
