"""Column details by relation, for the Inspector."""

from __future__ import annotations

from typing import Iterable

from harlequin.catalog import ColumnDetails


class SchemaIndex:
    def __init__(self, columns: Iterable[ColumnDetails]) -> None:
        self._columns: dict[str, list[ColumnDetails]] = {}
        for column in columns:
            self._columns.setdefault(column.relation, []).append(column)
        for listed in self._columns.values():
            listed.sort(key=lambda column: column.position)

    def __bool__(self) -> bool:
        return bool(self._columns)

    @property
    def relations(self) -> list[str]:
        return sorted(self._columns)

    def columns_of(self, relation: str) -> list[ColumnDetails]:
        return list(self._columns.get(relation, ()))

    def column(self, relation: str, written: str) -> ColumnDetails | None:
        """The column `written` names; unquoted names ignore case, like SQL."""
        from harlequin.navigate import split_path

        [(name, quoted)] = split_path(written)
        for column in self._columns.get(relation, ()):
            if column.name == name or (
                not quoted and column.name.casefold() == name.casefold()
            ):
                return column
        return None
