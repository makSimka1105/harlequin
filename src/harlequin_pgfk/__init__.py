"""The Postgres adapter, plus the foreign keys the Relations panel needs.

Foreign keys live here rather than in core because an edge is matched against a
`CatalogItem.qualified_identifier`, and only the adapter knows how its own
catalog spells one. Postgres spells a relation `"schema"."table"` -- the database
is NOT part of it, even though the tree shows databases above schemas -- so this
module spells edges the same way and matching stays a plain string comparison.

It subclasses rather than forks `harlequin-postgres`: that package keeps getting
releases, and everything except `get_foreign_keys()` should keep coming from it.
"""

from __future__ import annotations

from typing import Sequence

from harlequin_postgres.adapter import (
    HarlequinPostgresAdapter,
    HarlequinPostgresConnection,
)
from harlequin_postgres.loaders import register_inf_loaders

from harlequin.catalog import ForeignKeyEdge
from harlequin.exception import HarlequinConnectionError

FOREIGN_KEYS_SQL = """
select
    con.conname,
    src_ns.nspname,
    src.relname,
    array_agg(src_att.attname order by cols.ord),
    tgt_ns.nspname,
    tgt.relname,
    array_agg(tgt_att.attname order by cols.ord)
from pg_catalog.pg_constraint con
join pg_catalog.pg_class src on src.oid = con.conrelid
join pg_catalog.pg_namespace src_ns on src_ns.oid = src.relnamespace
join pg_catalog.pg_class tgt on tgt.oid = con.confrelid
join pg_catalog.pg_namespace tgt_ns on tgt_ns.oid = tgt.relnamespace
cross join lateral unnest(con.conkey, con.confkey)
    with ordinality as cols(src_attnum, tgt_attnum, ord)
join pg_catalog.pg_attribute src_att
    on src_att.attrelid = con.conrelid and src_att.attnum = cols.src_attnum
join pg_catalog.pg_attribute tgt_att
    on tgt_att.attrelid = con.confrelid and tgt_att.attnum = cols.tgt_attnum
where
    con.contype = 'f'
    and src_ns.nspname not in ('pg_catalog', 'information_schema')
group by 1, 2, 3, 5, 6
order by 2, 3, 1
"""
"""Every foreign key of the connected database, one row per constraint.

`unnest(conkey, confkey) with ordinality` walks the two column-number arrays in
step, so a key spanning several columns keeps its referencing and referenced
columns paired and in the order the constraint declares them.
"""


def _identifier(*labels: str) -> str:
    """Spell a catalog identifier the way the Postgres adapter's catalog does."""
    return ".".join(f'"{label}"' for label in labels)


class HarlequinPgFkConnection(HarlequinPostgresConnection):
    def get_foreign_keys(self) -> Sequence[ForeignKeyEdge]:
        """Read the connected database's foreign keys.

        Only that one database: a Postgres connection cannot see another's
        catalog, while Harlequin's tree may list several. Relations in the other
        databases simply have no edges, which is the same as having none.
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(FOREIGN_KEYS_SQL)
            rows = cur.fetchall()

        return [
            ForeignKeyEdge(
                constraint_name=name,
                from_relation=_identifier(from_schema, from_table),
                from_columns=tuple(from_columns),
                to_relation=_identifier(to_schema, to_table),
                to_columns=tuple(to_columns),
            )
            for (
                name,
                from_schema,
                from_table,
                from_columns,
                to_schema,
                to_table,
                to_columns,
            ) in rows
        ]


class HarlequinPgFkAdapter(HarlequinPostgresAdapter):
    def connect(self) -> HarlequinPgFkConnection:
        """Build the connection the parent would, as the subclass.

        The parent constructs its connection class by name, so there is no hook
        to substitute ours; these few lines mirror it deliberately. Keep them in
        step with `HarlequinPostgresAdapter.connect` when upstream changes it.
        """
        if len(self.conn_str) > 1:
            raise HarlequinConnectionError(
                "Cannot provide multiple connection strings to the Postgres adapter. "
                f"{self.conn_str}"
            )
        register_inf_loaders()
        return HarlequinPgFkConnection(self.conn_str, options=self.options)
