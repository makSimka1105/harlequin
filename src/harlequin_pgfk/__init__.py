"""The Postgres adapter plus the keys and column details the Inspector needs."""

from __future__ import annotations

from typing import Sequence

from harlequin_postgres.adapter import (
    HarlequinPostgresAdapter,
    HarlequinPostgresConnection,
)
from harlequin_postgres.loaders import register_inf_loaders

from harlequin.catalog import ColumnDetails, ForeignKeyEdge
from harlequin.exception import HarlequinConnectionError

# unnest ... with ordinality keeps a composite key's columns paired and ordered;
# conparentid = 0 drops the copies Postgres clones onto every partition
FOREIGN_KEYS_SQL = """
select
    con.conname,
    src_ns.nspname,
    src.relname,
    array_agg(src_att.attname order by cols.ord),
    tgt_ns.nspname,
    tgt.relname,
    array_agg(tgt_att.attname order by cols.ord),
    current_database(),
    bool_or(not src_att.attnotnull)
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
    and con.conparentid = 0
    and src_ns.nspname not in ('pg_catalog', 'information_schema')
group by 1, 2, 3, 5, 6
order by 2, 3, 1
"""

# indkey is an int2vector, indexed from 0: indkey[0] is an index's leading column
COLUMN_DETAILS_SQL = r"""
select
    ns.nspname,
    rel.relname,
    att.attname,
    att.attnum,
    pg_catalog.format_type(att.atttypid, att.atttypmod),
    not att.attnotnull,
    case
        when att.attidentity <> '' then 'identity'
        when att.attgenerated <> ''
            then 'generated as ' || pg_catalog.pg_get_expr(def.adbin, def.adrelid)
        else pg_catalog.pg_get_expr(def.adbin, def.adrelid)
    end,
    exists (
        select from pg_catalog.pg_index i
        where i.indrelid = rel.oid and i.indisprimary and att.attnum = any(i.indkey)
    ),
    exists (
        select from pg_catalog.pg_index i
        where
            i.indrelid = rel.oid
            and i.indisunique
            and not i.indisprimary
            and i.indnkeyatts = 1
            and i.indkey[0] = att.attnum
            and i.indpred is null
    ),
    exists (
        select from pg_catalog.pg_index i
        where i.indrelid = rel.oid and i.indkey[0] = att.attnum
    ),
    pg_catalog.col_description(rel.oid, att.attnum),
    current_database()
from pg_catalog.pg_attribute att
join pg_catalog.pg_class rel on rel.oid = att.attrelid
join pg_catalog.pg_namespace ns on ns.oid = rel.relnamespace
left join pg_catalog.pg_attrdef def
    on def.adrelid = att.attrelid and def.adnum = att.attnum
where
    att.attnum > 0
    and not att.attisdropped
    and rel.relkind in ('r', 'p', 'v', 'm', 'f')
    and not rel.relispartition
    and ns.nspname <> 'information_schema'
    and ns.nspname not like 'pg\_%'
order by 1, 2, 4
"""


def _identifier(*labels: str) -> str:
    """Spelled like the Postgres catalog: schema-qualified, database left out."""
    return ".".join(f'"{label}"' for label in labels)


class HarlequinPgFkConnection(HarlequinPostgresConnection):
    def get_foreign_keys(self) -> Sequence[ForeignKeyEdge]:
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
                # identifiers omit the database, so the edge has to name it
                database=database,
                nullable=nullable,
            )
            for (
                name,
                from_schema,
                from_table,
                from_columns,
                to_schema,
                to_table,
                to_columns,
                database,
                nullable,
            ) in rows
        ]

    def get_column_details(self) -> Sequence[ColumnDetails]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(COLUMN_DETAILS_SQL)
            rows = cur.fetchall()

        return [
            ColumnDetails(
                relation=_identifier(schema, table),
                name=name,
                position=position,
                type_name=type_name,
                nullable=nullable,
                default=default,
                primary_key=primary_key,
                unique=unique,
                indexed=indexed,
                comment=comment,
                database=database,
            )
            for (
                schema,
                table,
                name,
                position,
                type_name,
                nullable,
                default,
                primary_key,
                unique,
                indexed,
                comment,
                database,
            ) in rows
        ]


class HarlequinPgFkAdapter(HarlequinPostgresAdapter):
    def connect(self) -> HarlequinPgFkConnection:
        # mirrors HarlequinPostgresAdapter.connect, which has no class hook
        if len(self.conn_str) > 1:
            raise HarlequinConnectionError(
                "Cannot provide multiple connection strings to the Postgres adapter. "
                f"{self.conn_str}"
            )
        register_inf_loaders()
        return HarlequinPgFkConnection(self.conn_str, options=self.options)
