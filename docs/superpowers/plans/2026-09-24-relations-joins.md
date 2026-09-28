# Панель связей и сборка JOIN — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** панель связей отражает курсор каталога и позволяет ходить по FK, вставлять таблицу, поле или готовый JOIN; из редактора по `ctrl+l` открывается JOIN-пикер.

**Architecture:** чистое ядро `harlequin/relations/` (граф, разбор запроса, пути, сборка JOIN, кандидаты) без textual; `CatalogLookup` и `RelationsService` забирают логику вставки из `app.py`; панель и пикер — тонкие виджеты поверх сервиса.

**Tech Stack:** Python 3.10, textual 8.2.8, tree-sitter через `harlequin.statements.captures`, duckdb для функциональных тестов, pytest + pytest-asyncio + xdist.

**Spec:** `docs/superpowers/specs/2026-09-24-relations-joins-design.md`

## Global Constraints

- Репозиторий `~/src/harlequin`, ветка `maksibon-fork`. Python из `.venv/bin/python`.
- Одиночный тест: `.venv/bin/python -m pytest <path>::<name> -q -n0 -p no:cacheprovider`. Весь набор: `.venv/bin/python -m pytest tests -q -p no:cacheprovider`.
- Базовые падения окружения, не наши (сверять по ним): `test_config_schema` (нет `libodbc.so.2`), `test_duckdb::test_connect_prql`, `test_crash::test_a_crash_while_replaying_recovered_buffers_cannot_repeat`, `test_config_wizard::TestReadOnly`, `test_hsql::test_spec_*`/`test_info_*`/`test_config_schema_json_*`, `test_import_hygiene::test_config_schema_writes_a_document_and_reads_no_file`.
- Перед завершением задачи: `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`, `.venv/bin/mypy src/harlequin`.
- Комментарии: без абзацев. Докстринг — одна строка. Комментарий — только одна строка про неочевидное «почему». При переносе кода длинные докстринги и комментарии сокращаются до одной строки.
- Коммиты — только если пользователь разрешил их в этой сессии. Без разрешения шаг «Commit» пропускается, изменения остаются в дереве.
- В дереве лежат чужие незакоммиченные правки (`pyproject.toml`, `app.tcss` блок `:ansi`, `app_base.py`, `data_catalog/tree.py`, `test_data_catalog.py`). Их не трогать и в свои коммиты не добавлять: `git add` только перечисленных в задаче файлов.
- Тексты для пользователя (уведомления, пустые состояния) — по-русски, как в спеке.

## Review Focus

- Кириллица или другой не-ASCII текст в statement до места вставки: tree-sitter отдаёт байты, вставка должна попасть ровно после последнего join. Тест в Task 3.
- Два FK из одной таблицы в одну и ту же (billto/shipto): оба должны остаться отдельными кандидатами, иначе молча выберется не тот ключ. Тест в Task 4.
- Self-reference (`employee.managerid → employee`): новая таблица получает свой алиас, условие не сравнивает таблицу саму с собой. Тест в Task 4.
- Перечитывание графа (`refresh_catalog`), пока в панели пройден путь: путь сбрасывается, панель не показывает исчезнувшую связь. Тест в Task 7.
- `J` в пустом буфере: вставляется `from` + join в позицию курсора, без ведущего перевода строки. Тест в Task 6.

---

### Task 1: Пакет `relations/` — перенос без изменения поведения

**Files:**
- Create: `src/harlequin/relations/__init__.py` (пустой)
- Move: `src/harlequin/relations.py` → `src/harlequin/relations/graph.py`
- Move: `src/harlequin/references.py` → `src/harlequin/relations/scope.py` (часть) и `src/harlequin/relations/spelling.py` (часть)
- Modify: `src/harlequin/app.py` (импорты), `src/harlequin/components/relations_panel.py` (импорты)
- Modify: `tests/unit_tests/test_references.py` (импорты)

**Interfaces:**
- Produces: `harlequin.relations.graph.{RelationGraph, RelationLink, Route, DEFAULT_MAX_STEPS}`; `harlequin.relations.scope.{RelationRef, BufferScope, read_scope}`; `harlequin.relations.spelling.{path_for, split_identifier, DEFAULT_RESERVED, UNQUOTED}`.

- [ ] **Step 1: Перенести граф**

```bash
cd ~/src/harlequin
mkdir -p src/harlequin/relations
git mv src/harlequin/relations.py src/harlequin/relations/graph.py
touch src/harlequin/relations/__init__.py
```

В `graph.py` удалить функцию `split_identifier` (она уезжает в `spelling.py`) и добавить импорт `from harlequin.relations.spelling import split_identifier` — он нужен панели через `graph`, пока панель не переписана. Модульный докстринг и докстринги классов/методов сократить до одной строки каждый. Докстринг `DEFAULT_MAX_STEPS` удалить.

- [ ] **Step 2: Разделить `references.py`**

```bash
git mv src/harlequin/references.py src/harlequin/relations/scope.py
```

Из `scope.py` вырезать в новый файл `src/harlequin/relations/spelling.py`: `UNQUOTED`, `DEFAULT_RESERVED`, `path_for`, `_segments`, `_reproducible`, `_spell`, `_spell_segment` и импорт `KEYWORDS`. В `scope.py` остаются `RELATION_QUERY`, `CTE_QUERY`, `RelationRef`, `BufferScope`, `_suffix_matches`, `read_scope`, `_name_and_alias`. В `spelling.py` добавить перенесённую из графа функцию:

```python
def split_identifier(qualified_identifier: str) -> list[str]:
    from harlequin.navigate import split_path

    return [segment for segment, _ in split_path(qualified_identifier)]
```

`path_for` импортирует `BufferScope` для аннотации под `TYPE_CHECKING`:

```python
if TYPE_CHECKING:
    from harlequin.catalog import CatalogItem
    from harlequin.relations.scope import BufferScope
```

Все многоабзацные докстринги и комментарии в обоих файлах сократить до одной строки.

- [ ] **Step 3: Поправить импорты**

`src/harlequin/app.py`:

```python
from harlequin.relations.graph import RelationGraph
from harlequin.relations.scope import read_scope
from harlequin.relations.spelling import DEFAULT_RESERVED, path_for
```

(заменяют `from harlequin.references import DEFAULT_RESERVED, path_for, read_scope` и `from harlequin.relations import RelationGraph`).

`src/harlequin/components/relations_panel.py`:

```python
from harlequin.relations.graph import RelationGraph, RelationLink, Route
from harlequin.relations.spelling import split_identifier
```

`tests/unit_tests/test_references.py`:

```python
from harlequin.relations.scope import BufferScope, RelationRef, read_scope
from harlequin.relations.spelling import DEFAULT_RESERVED, path_for
```

Проверить, что старых импортов не осталось: `grep -rn "harlequin.references\|from harlequin.relations import" src tests` — пусто.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_references.py tests/functional_tests/test_data_catalog.py -q -p no:cacheprovider`
Expected: всё PASS, как до переноса.

- [ ] **Step 5: Commit**

```bash
git add src/harlequin/relations src/harlequin/app.py src/harlequin/components/relations_panel.py tests/unit_tests/test_references.py
git commit -m "refactor: move relation graph and path spelling into a relations package"
```

---

### Task 2: Граф с направлением и nullable, `pgfk` читает nullable

**Files:**
- Modify: `src/harlequin/catalog.py` (`ForeignKeyEdge`)
- Modify: `src/harlequin/relations/graph.py`
- Modify: `src/harlequin/components/relations_panel.py` (только адаптация под новые имена)
- Modify: `src/harlequin_pgfk/__init__.py`
- Test: `tests/unit_tests/test_relations_graph.py` (новый), `tests/unit_tests/test_pgfk.py` (новый)

**Interfaces:**
- Consumes: `split_identifier` из Task 1.
- Produces:
  - `ForeignKeyEdge(..., database: str | None = None, nullable: bool = False)`
  - `Direction = Literal["out", "in"]`
  - `Link(edge, direction)` с свойствами `near_relation`, `far_relation`, `near_columns`, `far_columns`, `cardinality -> str` (`"N:1"`/`"1:N"`), `nullable -> bool`
  - `Route(steps: tuple[Link, ...])` со свойствами `source`, `target`, `__len__`
  - `RelationGraph(edges)`: `__bool__`, `covers(database)`, `relations -> list[str]`, `links_for(relation) -> list[Link]`, `relation_of(identifier) -> tuple[str, str | None] | None`, `routes_from(relation, max_steps=4) -> list[Route]`

- [ ] **Step 1: Написать тесты графа**

`tests/unit_tests/test_relations_graph.py`:

```python
from __future__ import annotations

from harlequin.catalog import ForeignKeyEdge
from harlequin.relations.graph import RelationGraph


def edge(
    src: str, src_col: str, dst: str, dst_col: str, nullable: bool = False
) -> ForeignKeyEdge:
    return ForeignKeyEdge(
        constraint_name=f"{src}_{src_col}",
        from_relation=f'"s"."{src}"',
        from_columns=(src_col,),
        to_relation=f'"s"."{dst}"',
        to_columns=(dst_col,),
        nullable=nullable,
    )


GRAPH = RelationGraph(
    [
        edge("orders", "customerid", "customer", "customerid", nullable=True),
        edge("orderline", "orderid", "orders", "orderid"),
        edge("orderline", "productid", "product", "productid"),
    ]
)


def test_links_are_seen_from_both_ends() -> None:
    [out] = GRAPH.links_for('"s"."orders"')[:1]
    assert out.direction == "out"
    assert out.far_relation == '"s"."customer"'
    assert out.cardinality == "N:1"

    [incoming] = GRAPH.links_for('"s"."customer"')
    assert incoming.direction == "in"
    assert incoming.far_relation == '"s"."orders"'
    assert incoming.cardinality == "1:N"


def test_nullable_only_applies_to_the_referencing_end() -> None:
    [out] = [
        link for link in GRAPH.links_for('"s"."orders"') if link.direction == "out"
    ]
    [incoming] = GRAPH.links_for('"s"."customer"')
    assert out.nullable
    assert not incoming.nullable


def test_links_are_sorted_by_far_relation() -> None:
    far = [link.far_relation for link in GRAPH.links_for('"s"."orderline"')]
    assert far == ['"s"."orders"', '"s"."product"']


def test_relation_of_a_column_is_its_table() -> None:
    assert GRAPH.relation_of('"s"."orders"."customerid"') == (
        '"s"."orders"',
        "customerid",
    )
    assert GRAPH.relation_of('"s"."orders"') == ('"s"."orders"', None)
    assert GRAPH.relation_of('"s"."nowhere"') is None


def test_routes_skip_direct_neighbours_and_record_their_source() -> None:
    routes = GRAPH.routes_from('"s"."customer"')
    assert [route.target for route in routes] == [
        '"s"."orderline"',
        '"s"."product"',
    ]
    assert all(route.source == '"s"."customer"' for route in routes)
    assert [len(route) for route in routes] == [2, 3]


def test_a_self_reference_is_a_link_to_itself() -> None:
    graph = RelationGraph([edge("employee", "managerid", "employee", "employeeid")])
    directions = sorted(
        link.direction for link in graph.links_for('"s"."employee"')
    )
    assert directions == ["in", "out"]
    assert graph.routes_from('"s"."employee"') == []
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_graph.py -q -n0 -p no:cacheprovider`
Expected: FAIL — `ForeignKeyEdge` не принимает `nullable`.

- [ ] **Step 3: `ForeignKeyEdge.nullable`**

В `src/harlequin/catalog.py` в конец полей `ForeignKeyEdge` после `database`:

```python
    nullable: bool = False
    """Whether a referencing column may hold null."""
```

- [ ] **Step 4: Переписать `graph.py`**

`src/harlequin/relations/graph.py` целиком:

```python
"""Foreign keys as a graph over relations."""

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
```

- [ ] **Step 5: Адаптировать старую панель под новые имена**

В `src/harlequin/components/relations_panel.py`:
- импорт `RelationLink` → `Link`, аннотации `list[RelationLink]` → `list[Link]`;
- `link.outgoing` → `link.direction == "out"`;
- `self.graph.links_for_relation(x)` → `self.graph.links_for(x)`;
- `self.graph.links_for_column(relation, column)` → `[link for link in self.graph.links_for(relation) if column in link.near_columns]`;
- метод `_as_relation_and_column` удалить, в `show()` вместо него:

```python
        found = self.graph.relation_of(qualified_identifier)
        if found is None:
            self._note(root, "select a table or a column")
            return
        relation, column = found
```

- [ ] **Step 6: Тест `pgfk`**

`tests/unit_tests/test_pgfk.py`:

```python
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from harlequin_pgfk import HarlequinPgFkConnection


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, sql: str) -> None:
        pass

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class FakePool:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    @contextmanager
    def connection(self) -> Iterator[Any]:
        conn = type("Conn", (), {"cursor": lambda _self: FakeCursor(self.rows)})()
        yield conn


def test_foreign_keys_carry_nullability() -> None:
    connection = HarlequinPgFkConnection.__new__(HarlequinPgFkConnection)
    connection.pool = FakePool(  # type: ignore[assignment]
        [
            (
                "customer_personid_fkey",
                "sales",
                "customer",
                ["personid"],
                "person",
                "person",
                ["personid"],
                "retail_training",
                True,
            )
        ]
    )

    [edge] = connection.get_foreign_keys()

    assert edge.from_relation == '"sales"."customer"'
    assert edge.to_columns == ("personid",)
    assert edge.database == "retail_training"
    assert edge.nullable is True
```

Run: `.venv/bin/python -m pytest tests/unit_tests/test_pgfk.py -q -n0 -p no:cacheprovider`
Expected: FAIL — распаковка строки из 9 полей в 8.

- [ ] **Step 7: Nullable в запросе `pgfk`**

В `FOREIGN_KEYS_SQL` после `current_database()` добавить колонку:

```sql
    current_database(),
    bool_or(not src_att.attnotnull)
```

В `get_foreign_keys` добавить `nullable=nullable` в конструктор `ForeignKeyEdge` и `nullable` последним элементом распаковки кортежа строки. Докстринг `FOREIGN_KEYS_SQL`, модульный докстринг и докстринги методов сократить до одной строки.

- [ ] **Step 8: Прогнать тесты и проверить на живой базе**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_graph.py tests/unit_tests/test_pgfk.py tests/functional_tests/test_data_catalog.py -q -p no:cacheprovider`
Expected: PASS.

Проверка запроса на учебной базе (если поднята, `./bin/db up` в `~/itmo/02-databases/sql-course`):

```bash
cd ~/src/harlequin && .venv/bin/python -c "
import psycopg
from harlequin_pgfk import FOREIGN_KEYS_SQL
with psycopg.connect('host=localhost dbname=retail_training') as c:
    for row in c.execute(FOREIGN_KEYS_SQL): print(row[2], row[3], row[-1])"
```

Expected: 10 строк; `customer ['personid'] True`, `salesorderheader ['customerid'] True`, у `salesorderdetail` — `False`.

- [ ] **Step 9: Commit**

```bash
git add src/harlequin/catalog.py src/harlequin/relations/graph.py src/harlequin/components/relations_panel.py src/harlequin_pgfk/__init__.py tests/unit_tests/test_relations_graph.py tests/unit_tests/test_pgfk.py
git commit -m "feat: give relation links a direction, cardinality and nullability"
```

---

### Task 3: Scope знает верхний уровень и точку вставки; `statement_span_at`

**Files:**
- Modify: `src/harlequin/relations/scope.py`
- Modify: `src/harlequin/statements.py`
- Test: `tests/unit_tests/test_relations_scope.py` (новый), `tests/unit_tests/test_references.py` (одно ожидание), `tests/unit_tests/test_statements.py`

**Interfaces:**
- Produces:
  - `RelationRef(name, alias, is_cte, top_level: bool = True)` со свойством `reference -> str` (алиас или имя)
  - `BufferScope(relations, anchor: int | None = None, indent: str = "")` с методами `alias_for(identifier, known_relations=())` (поведение прежнее), `reference_for(identifier, known_relations=()) -> str | None`, `position_of(identifier, known_relations=()) -> int | None`, `taken_names() -> set[str]`
  - `StatementSpan(start: int, text: str)`; `statement_span_at(text: str, point: tuple[int, int]) -> StatementSpan | None`

- [ ] **Step 1: Тесты scope**

`tests/unit_tests/test_relations_scope.py`:

```python
from __future__ import annotations

from harlequin.relations.scope import read_scope

CUSTOMER = '"db"."sales"."customer"'
STORE = '"db"."sales"."store"'


def test_anchor_is_after_the_last_join() -> None:
    sql = (
        "select *\n  from sales.customer c\n"
        "  join sales.store s on s.id = c.id\n  where true"
    )
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("on s.id = c.id")
    assert scope.indent == "  "


def test_anchor_is_after_the_from_relation_without_joins() -> None:
    sql = "select * from sales.customer c, sales.store s where 1 = 1"
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("sales.store s")


def test_no_from_has_no_anchor() -> None:
    assert read_scope("select 1").anchor is None


def test_a_half_written_join_anchors_after_the_from() -> None:
    sql = "select * from sales.customer c\njoin "
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("sales.customer c")


def test_subquery_and_cte_bodies_are_not_top_level() -> None:
    sql = (
        "with r as (select * from sales.store s1) "
        "select * from (select * from sales.store s2) x "
        "join sales.customer c on true"
    )
    top = {ref.name for ref in read_scope(sql).relations if ref.top_level}
    assert top == {"sales.customer"}


def test_anchor_counts_characters_not_bytes() -> None:
    sql = "-- заказы покупателей\nselect * from sales.customer c\nwhere true"
    scope = read_scope(sql)
    assert sql[: scope.anchor].endswith("sales.customer c")


def test_reference_is_the_alias_or_the_written_name() -> None:
    scope = read_scope("select * from sales.customer c join sales.store on true")
    assert scope.reference_for(CUSTOMER) == "c"
    assert scope.reference_for(STORE) == "sales.store"
    assert scope.position_of(STORE) == 1


def test_reference_ignores_relations_inside_subqueries() -> None:
    scope = read_scope("select * from (select * from sales.store s) x")
    assert scope.reference_for(STORE) is None
    assert scope.alias_for(STORE) == "s"


def test_taken_names_are_aliases_and_bare_table_names() -> None:
    scope = read_scope("select * from sales.customer C join sales.store on true")
    assert scope.taken_names() == {"c", "store"}
```

- [ ] **Step 2: Тест `statement_span_at`**

Дописать в `tests/unit_tests/test_statements.py`:

```python
from harlequin.statements import StatementSpan, statement_span_at


def test_statement_span_points_at_the_stripped_statement() -> None:
    text = "select 1;\n\n  select 2 from t;"
    span = statement_span_at(text, (2, 4))
    assert span == StatementSpan(start=13, text="select 2 from t;")
    assert text[span.start :].startswith("select 2")


def test_statement_span_of_a_single_statement_is_the_whole_text() -> None:
    assert statement_span_at("select 1", (0, 3)) == StatementSpan(0, "select 1")


def test_statement_span_in_blank_space_is_none() -> None:
    assert statement_span_at("select 1;\n\n", (1, 0)) is None
```

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_scope.py tests/unit_tests/test_statements.py -q -n0 -p no:cacheprovider`
Expected: FAIL — нет `anchor`, `reference_for`, `statement_span_at`.

- [ ] **Step 3: `statement_span_at`**

В `src/harlequin/statements.py` рядом с `statement_at`:

```python
@dataclass(frozen=True)
class StatementSpan:
    start: int
    """Character offset of `text` in the buffer."""
    text: str


def statement_span_at(text: str, point: Point) -> StatementSpan | None:
    """The statement under `point` and where it starts, or None in blank space."""
    if not text.strip():
        return None

    offsets = _separator_offsets(text)
    if not offsets:
        return StatementSpan(start=0, text=text)

    lines = text.splitlines(keepends=True)
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line))

    row = min(max(point[0], 0), len(lines) - 1)
    target = line_starts[row] + point[1]

    start = 0
    for end in [*offsets, len(text)]:
        if start <= target <= end:
            raw = text[start:end]
            sql = raw.strip()
            if not sql:
                return None
            return StatementSpan(start=start + len(raw) - len(raw.lstrip()), text=sql)
        start = end
    return None


def statement_at(text: str, point: Point) -> str | None:
    """The statement whose span contains `point`, or None if none does."""
    span = statement_span_at(text, point)
    return span.text if span is not None else None
```

Старое тело `statement_at` удалить. Если `dataclass` ещё не импортирован в `statements.py`, добавить `from dataclasses import dataclass`.

- [ ] **Step 4: Расширить `scope.py`**

Константы и `RelationRef`:

```python
RELATION_QUERY = "(relation) @relation"
JOIN_QUERY = "(join) @join"
CTE_QUERY = "(cte (identifier) @name) @cte"
NESTED = frozenset({"subquery", "cte"})


@dataclass(frozen=True)
class RelationRef:
    name: str
    alias: str | None
    is_cte: bool
    top_level: bool = True

    @property
    def reference(self) -> str:
        return self.alias or self.name
```

`BufferScope`:

```python
@dataclass(frozen=True)
class BufferScope:
    relations: tuple[RelationRef, ...] = field(default=())
    anchor: int | None = None
    """Character offset right after the last top-level join or from relation."""
    indent: str = ""

    def alias_for(
        self, qualified_identifier: str, known_relations: Iterable[str] = ()
    ) -> str | None:
        """The one alias the buffer gives this relation, if exactly one."""
        aliases = [
            ref.alias
            for _, ref in self._matches(qualified_identifier, known_relations)
            if ref.alias is not None
        ]
        return aliases[0] if len(aliases) == 1 else None

    def reference_for(
        self, qualified_identifier: str, known_relations: Iterable[str] = ()
    ) -> str | None:
        position = self.position_of(qualified_identifier, known_relations)
        return None if position is None else self.relations[position].reference

    def position_of(
        self, qualified_identifier: str, known_relations: Iterable[str] = ()
    ) -> int | None:
        """Where the top-level query names this relation, if exactly once."""
        found = [
            index
            for index, ref in self._matches(qualified_identifier, known_relations)
            if ref.top_level
        ]
        return found[0] if len(found) == 1 else None

    def taken_names(self) -> set[str]:
        from harlequin.navigate import split_path

        return {
            split_path(ref.reference)[-1][0].casefold()
            for ref in self.relations
            if ref.top_level
        }

    def _matches(
        self, qualified_identifier: str, known_relations: Iterable[str]
    ) -> list[tuple[int, RelationRef]]:
        from harlequin.navigate import split_path

        target = split_path(qualified_identifier)
        catalog_paths = [split_path(identifier) for identifier in known_relations]
        matches: list[tuple[int, RelationRef]] = []
        for index, ref in enumerate(self.relations):
            if ref.is_cte:
                continue
            written = split_path(ref.name)
            if not _suffix_matches(written, target):
                continue
            if sum(1 for path in catalog_paths if _suffix_matches(written, path)) > 1:
                continue
            matches.append((index, ref))
        return matches
```

`read_scope`:

```python
def read_scope(text: str) -> BufferScope:
    if not text.strip():
        return BufferScope()

    from harlequin.statements import captures

    cte_names = {
        node.text.decode("utf-8").casefold()
        for node in captures(text, CTE_QUERY).get("name", [])
        if node.text is not None
    }

    relations: list[RelationRef] = []
    clause_ends: list[Node] = []
    for node in sorted(
        captures(text, RELATION_QUERY).get("relation", []),
        key=lambda found: found.start_byte,
    ):
        top_level = _is_top_level(node)
        if top_level:
            clause_ends.append(node)
        name, alias = _name_and_alias(node)
        if name:
            relations.append(
                RelationRef(
                    name=name,
                    alias=alias,
                    is_cte=name.casefold() in cte_names,
                    top_level=top_level,
                )
            )
    clause_ends.extend(
        node for node in captures(text, JOIN_QUERY).get("join", []) if _is_top_level(node)
    )
    if not clause_ends:
        return BufferScope(relations=tuple(relations))

    last = max(clause_ends, key=lambda node: node.end_byte)
    encoded = text.encode("utf-8")
    anchor = len(encoded[: last.end_byte].decode("utf-8"))
    start = len(encoded[: last.start_byte].decode("utf-8"))
    line = text[text.rfind("\n", 0, start) + 1 :]
    indent = line[: len(line) - len(line.lstrip(" \t"))]
    return BufferScope(relations=tuple(relations), anchor=anchor, indent=indent)


def _is_top_level(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in NESTED:
            return False
        parent = parent.parent
    return True
```

- [ ] **Step 5: Поправить ожидание в старом тесте**

В `tests/unit_tests/test_references.py::test_read_scope_finds_aliases_and_bare_relations` первая ожидаемая запись лежит в теле CTE:

```python
        RelationRef(
            name="sales.salesorderheader", alias=None, is_cte=False, top_level=False
        ),
```

- [ ] **Step 6: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_scope.py tests/unit_tests/test_references.py tests/unit_tests/test_statements.py tests/functional_tests/test_data_catalog.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/harlequin/relations/scope.py src/harlequin/statements.py tests/unit_tests/test_relations_scope.py tests/unit_tests/test_references.py tests/unit_tests/test_statements.py
git commit -m "feat: read where the next join goes from the statement under the cursor"
```

---

### Task 4: Сборка JOIN и кандидаты

**Files:**
- Modify: `src/harlequin/relations/spelling.py` (`spell_relation`, `spell_segment`, `table_name`)
- Create: `src/harlequin/relations/joins.py`, `src/harlequin/relations/candidates.py`
- Test: `tests/unit_tests/test_relations_joins.py`

**Interfaces:**
- Consumes: `Link`, `Route`, `RelationGraph` (Task 2); `BufferScope`, `read_scope` (Task 3).
- Produces:
  - `spelling.spell_segment(segment, reserved) -> str` (бывшая `_spell_segment`), `spell_relation(identifier, reserved) -> str`, `table_name(identifier) -> str`
  - `JoinPlan(anchor: int | None, text: str)`, `JoinRefusal(reason: str)`
  - `plan_joins(route, scope, reserved, known_relations=()) -> JoinPlan | JoinRefusal`
  - `new_alias(identifier, taken: set[str], reserved) -> str` (добавляет результат в `taken`)
  - `join_candidates(scope, graph, known_relations=()) -> list[Route]`

- [ ] **Step 1: Тесты**

`tests/unit_tests/test_relations_joins.py`:

```python
from __future__ import annotations

from harlequin.catalog import ForeignKeyEdge
from harlequin.relations.candidates import join_candidates
from harlequin.relations.graph import RelationGraph, Route
from harlequin.relations.joins import JoinPlan, JoinRefusal, new_alias, plan_joins
from harlequin.relations.scope import read_scope
from harlequin.relations.spelling import DEFAULT_RESERVED


def rel(name: str) -> str:
    return f'"db"."shop"."{name}"'


def edge(
    src: str,
    src_cols: tuple[str, ...],
    dst: str,
    dst_cols: tuple[str, ...],
    nullable: bool = False,
    name: str | None = None,
) -> ForeignKeyEdge:
    return ForeignKeyEdge(
        constraint_name=name or f"{src}_{dst}",
        from_relation=rel(src),
        from_columns=src_cols,
        to_relation=rel(dst),
        to_columns=dst_cols,
        nullable=nullable,
    )


GRAPH = RelationGraph(
    [
        edge("orders", ("customerid",), "customer", ("customerid",), nullable=True),
        edge("orderline", ("orderid",), "orders", ("orderid",)),
        edge("orderline", ("productid",), "product", ("productid",)),
    ]
)


def route(*pairs: tuple[str, str]) -> Route:
    steps = []
    for near, far in pairs:
        [link] = [
            link for link in GRAPH.links_for(rel(near)) if link.far_relation == rel(far)
        ]
        steps.append(link)
    return Route(tuple(steps))


def plan(sql: str, r: Route, graph_reserved: frozenset[str] = DEFAULT_RESERVED):
    return plan_joins(r, read_scope(sql), graph_reserved)


def test_one_step_goes_under_the_last_join() -> None:
    sql = "select *\nfrom shop.orders o\njoin shop.orderline ol on ol.orderid = o.orderid"
    result = plan(sql, route(("orders", "customer")))
    assert isinstance(result, JoinPlan)
    assert result.anchor == len(sql)
    assert result.text == (
        "\nleft join shop.customer c on c.customerid = o.customerid"
    )


def test_an_incoming_link_is_an_inner_join() -> None:
    result = plan("select * from shop.customer c", route(("customer", "orders")))
    assert isinstance(result, JoinPlan)
    assert result.text == "\njoin shop.orders o on o.customerid = c.customerid"


def test_a_chain_reuses_a_table_already_in_the_query() -> None:
    sql = "select * from shop.customer c join shop.orders ord on true"
    result = plan(sql, route(("customer", "orders"), ("orders", "orderline")))
    assert isinstance(result, JoinPlan)
    assert result.text == "\njoin shop.orderline o on o.orderid = ord.orderid"


def test_aliases_do_not_collide() -> None:
    sql = "select * from shop.customer c"
    result = plan(sql, route(("customer", "orders"), ("orders", "orderline")))
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "\njoin shop.orders o on o.customerid = c.customerid"
        "\njoin shop.orderline o2 on o2.orderid = o.orderid"
    )


def test_a_composite_key_joins_on_every_column() -> None:
    graph = RelationGraph(
        [edge("line", ("orderid", "lineno"), "orderline", ("orderid", "lineno"))]
    )
    [link] = graph.links_for(rel("line"))
    result = plan_joins(
        Route((link,)), read_scope("select * from shop.line l"), DEFAULT_RESERVED
    )
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "\njoin shop.orderline o on o.orderid = l.orderid and o.lineno = l.lineno"
    )


def test_a_self_reference_gets_its_own_alias() -> None:
    graph = RelationGraph(
        [edge("employee", ("managerid",), "employee", ("employeeid",), nullable=True)]
    )
    [out] = [link for link in graph.links_for(rel("employee")) if link.direction == "out"]
    result = plan_joins(
        Route((out,)), read_scope("select * from shop.employee e"), DEFAULT_RESERVED
    )
    assert isinstance(result, JoinPlan)
    assert result.text == (
        "\nleft join shop.employee e2 on e2.employeeid = e.managerid"
    )


def test_without_a_from_the_plan_starts_with_one() -> None:
    result = plan("select 1", route(("customer", "orders")))
    assert result == JoinPlan(
        anchor=None,
        text="from shop.customer c\njoin shop.orders o on o.customerid = c.customerid",
    )


def test_a_query_without_the_source_is_refused() -> None:
    result = plan("select * from shop.product p", route(("customer", "orders")))
    assert result == JoinRefusal("customer нет в запросе")


def test_a_route_already_in_the_query_is_refused() -> None:
    sql = "select * from shop.customer c join shop.orders o on true"
    assert isinstance(plan(sql, route(("customer", "orders"))), JoinRefusal)


def test_new_alias_abbreviates_snake_case_and_skips_reserved() -> None:
    taken: set[str] = set()
    assert new_alias(rel("sales_order"), taken, DEFAULT_RESERVED) == "so"
    assert new_alias(rel("sales_order"), taken, DEFAULT_RESERVED) == "so2"
    assert new_alias(rel("as"), set(), frozenset({"a"})) == "a2"


def test_candidates_cover_every_table_in_the_query() -> None:
    scope = read_scope("select * from shop.customer c join shop.orders o on true")
    targets = [r.target for r in join_candidates(scope, GRAPH)]
    assert targets == [rel("orderline"), rel("product")]
    assert [len(r) for r in join_candidates(scope, GRAPH)] == [1, 2]


def test_two_keys_to_the_same_table_stay_separate_candidates() -> None:
    graph = RelationGraph(
        [
            edge("orders", ("billto",), "address", ("addressid",), name="bill"),
            edge("orders", ("shipto",), "address", ("addressid",), name="ship"),
        ]
    )
    candidates = join_candidates(read_scope("select * from shop.orders o"), graph)
    assert [r.steps[0].near_columns for r in candidates] == [("billto",), ("shipto",)]
```

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_joins.py -q -n0 -p no:cacheprovider`
Expected: FAIL — нет модулей `joins`, `candidates`.

- [ ] **Step 2: Функции спеллинга**

В `src/harlequin/relations/spelling.py` переименовать `_spell_segment` в `spell_segment` (и вызов в `_spell`), добавить:

```python
def spell_relation(qualified_identifier: str, reserved: frozenset[str]) -> str:
    """`schema.table`, the part of a relation's identifier a query writes."""
    return _spell(split_identifier(qualified_identifier)[-2:], reserved)


def table_name(qualified_identifier: str) -> str:
    return split_identifier(qualified_identifier)[-1]
```

- [ ] **Step 3: `joins.py`**

```python
"""Join clauses for a route, written into the statement under the cursor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from harlequin.relations.graph import Link, Route
from harlequin.relations.scope import BufferScope
from harlequin.relations.spelling import (
    UNQUOTED,
    spell_relation,
    spell_segment,
    table_name,
)


@dataclass(frozen=True)
class JoinPlan:
    anchor: int | None
    """Statement offset to insert at; None inserts at the cursor."""
    text: str


@dataclass(frozen=True)
class JoinRefusal:
    reason: str


def plan_joins(
    route: Route,
    scope: BufferScope,
    reserved: frozenset[str],
    known_relations: Iterable[str] = (),
) -> JoinPlan | JoinRefusal:
    known = list(known_relations)
    taken = scope.taken_names()
    lines: list[str] = []

    current = scope.reference_for(route.source, known)
    if current is None:
        if scope.anchor is not None:
            return JoinRefusal(f"{table_name(route.source)} нет в запросе")
        current = new_alias(route.source, taken, reserved)
        lines.append(f"from {spell_relation(route.source, reserved)} {current}")

    joined = False
    for link in route.steps:
        self_reference = link.far_relation == link.near_relation
        present = None if self_reference else scope.reference_for(link.far_relation, known)
        if present is not None:
            current = present
            continue
        alias = new_alias(link.far_relation, taken, reserved)
        lines.append(_join_line(link, alias, current, reserved))
        current = alias
        joined = True

    if not joined:
        return JoinRefusal(f"{table_name(route.target)} уже в запросе")
    if scope.anchor is None:
        return JoinPlan(anchor=None, text="\n".join(lines))
    return JoinPlan(
        anchor=scope.anchor, text="".join(f"\n{scope.indent}{line}" for line in lines)
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
        f"{alias}.{spell_segment(far, reserved)} = {known}.{spell_segment(near, reserved)}"
        for near, far in zip(link.near_columns, link.far_columns)
    )
    return f"{kind} {spell_relation(link.far_relation, reserved)} {alias} on {condition}"
```

Строка с `condition` длиннее 88 символов — `ruff format` перенесёт её сам; после форматирования проверить `ruff check`.

- [ ] **Step 4: `candidates.py`**

```python
"""What the statement under the cursor can be joined to."""

from __future__ import annotations

from typing import Iterable

from harlequin.relations.graph import RelationGraph, Route
from harlequin.relations.scope import BufferScope


def join_candidates(
    scope: BufferScope, graph: RelationGraph, known_relations: Iterable[str] = ()
) -> list[Route]:
    """Direct links first, one per key; then the shortest route to each other table."""
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
            if link.far_relation not in present_ids:
                direct.append(Route((link,)))
        for route in graph.routes_from(relation):
            best = routed.get(route.target)
            if route.target not in present_ids and (best is None or len(route) < len(best)):
                routed[route.target] = route

    direct_targets = {route.target for route in direct}
    further = [
        route for target, route in routed.items() if target not in direct_targets
    ]
    return direct + sorted(further, key=lambda route: (len(route), route.target))
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_joins.py tests/unit_tests/test_references.py -q -n0 -p no:cacheprovider`
Expected: PASS. Затем `.venv/bin/ruff format src/harlequin/relations tests/unit_tests/test_relations_joins.py && .venv/bin/ruff check src tests && .venv/bin/mypy src/harlequin`.

- [ ] **Step 6: Commit**

```bash
git add src/harlequin/relations tests/unit_tests/test_relations_joins.py
git commit -m "feat: plan join clauses for a route and list join candidates"
```

---

### Task 5: `CatalogLookup` и `RelationsService` — вынос из `app.py`

**Files:**
- Create: `src/harlequin/catalog_lookup.py`, `src/harlequin/relations_service.py`
- Modify: `src/harlequin/app.py`
- Test: `tests/unit_tests/test_relations_service.py`

**Interfaces:**
- Consumes: всё из Tasks 2–4; `StatementSpan`, `statement_span_at` (Task 3).
- Produces:
  - `CatalogLookup(catalog: Catalog | None, on_loaded: Callable[[CatalogItem, list[CatalogItem]], None])`: `find(identifier, database) -> tuple[CatalogItem, CatalogItem | None] | None`, `known_relations() -> frozenset[str]`
  - `Edit(offset: int | None, text: str)`; `JoinCandidate(route: Route, source: str, preview: str)`
  - `RelationsService(on_loaded)`: атрибуты `graph`, `reserved`; методы `update_catalog(catalog)`, `path_for_item(item, owner, statement: str) -> str`, `path_text(identifier, database, statement: str) -> str | None`, `join_edit(route, statement: StatementSpan | None) -> Edit | JoinRefusal`, `join_candidates(statement: StatementSpan | None) -> list[JoinCandidate]`
  - в `Harlequin`: `self.relations: RelationsService`, `_statement() -> StatementSpan | None`, `_statement_text() -> str`

- [ ] **Step 1: Тесты сервиса**

`tests/unit_tests/test_relations_service.py`:

```python
from __future__ import annotations

from harlequin.catalog import Catalog, CatalogItem, ForeignKeyEdge
from harlequin.relations.graph import RelationGraph, Route
from harlequin.relations.joins import JoinRefusal
from harlequin.relations_service import Edit, RelationsService
from harlequin.statements import StatementSpan


def item(identifier: str, query_name: str, children: list[CatalogItem]) -> CatalogItem:
    return CatalogItem(
        qualified_identifier=identifier,
        query_name=query_name,
        label=identifier.rsplit(".", 1)[-1].strip('"'),
        type_label="t",
        children=children,
    )


CUSTOMERID = item('"db"."shop"."customer"."customerid"', '"customerid"', [])
CUSTOMER = item('"db"."shop"."customer"', '"shop"."customer"', [CUSTOMERID])
ORDERS = item('"db"."shop"."orders"', '"shop"."orders"', [])
CATALOG = Catalog(
    items=[item('"db"', '"db"', [item('"db"."shop"', '"shop"', [CUSTOMER, ORDERS])])]
)
EDGE = ForeignKeyEdge(
    constraint_name="orders_customer",
    from_relation='"db"."shop"."orders"',
    from_columns=("customerid",),
    to_relation='"db"."shop"."customer"',
    to_columns=("customerid",),
    nullable=True,
)


def service() -> RelationsService:
    relations = RelationsService(on_loaded=lambda parent, children: None)
    relations.update_catalog(CATALOG)
    relations.graph = RelationGraph([EDGE])
    return relations


def orders_to_customer(relations: RelationsService) -> Route:
    [link] = [
        link
        for link in relations.graph.links_for('"db"."shop"."orders"')
        if link.direction == "out"
    ]
    return Route((link,))


def test_path_text_uses_the_alias_in_the_statement() -> None:
    text = service().path_text(
        '"db"."shop"."customer"."customerid"', "db", "select * from shop.customer c"
    )
    assert text == "c.customerid"


def test_path_text_of_an_unknown_identifier_is_none() -> None:
    assert service().path_text('"db"."shop"."nope"', "db", "") is None


def test_known_relations_are_the_loaded_tables() -> None:
    known = service().lookup.known_relations()
    assert known == frozenset({'"db"."shop"."customer"', '"db"."shop"."orders"'})


def test_join_edit_is_an_absolute_offset() -> None:
    relations = service()
    statement = StatementSpan(start=10, text="select * from shop.orders o")
    edit = relations.join_edit(orders_to_customer(relations), statement)
    assert edit == Edit(
        offset=10 + len(statement.text),
        text="\nleft join shop.customer c on c.customerid = o.customerid",
    )


def test_join_edit_in_an_empty_buffer_starts_a_from_at_the_cursor() -> None:
    relations = service()
    edit = relations.join_edit(orders_to_customer(relations), None)
    assert edit == Edit(
        offset=None,
        text="from shop.orders o\nleft join shop.customer c on c.customerid = o.customerid",
    )


def test_join_edit_after_a_select_without_from_starts_on_a_new_line() -> None:
    relations = service()
    edit = relations.join_edit(
        orders_to_customer(relations), StatementSpan(0, "select o.orderid")
    )
    assert isinstance(edit, Edit)
    assert edit.offset is None
    assert edit.text.startswith("\nfrom shop.orders o")


def test_join_edit_refuses_a_query_without_the_source() -> None:
    relations = service()
    edit = relations.join_edit(
        orders_to_customer(relations), StatementSpan(0, "select * from shop.x x")
    )
    assert isinstance(edit, JoinRefusal)


def test_candidates_carry_the_source_reference_and_a_preview() -> None:
    [candidate] = service().join_candidates(
        StatementSpan(0, "select * from shop.orders o")
    )
    assert candidate.source == "o"
    assert candidate.preview == (
        "left join shop.customer c on c.customerid = o.customerid"
    )
```

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_service.py -q -n0 -p no:cacheprovider`
Expected: FAIL — нет `harlequin.relations_service`.

- [ ] **Step 2: `catalog_lookup.py`**

```python
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
```

- [ ] **Step 3: `relations_service.py`**

```python
"""Everything the app asks about relations, behind one object."""

from __future__ import annotations

from dataclasses import dataclass

from harlequin.catalog import Catalog, CatalogItem
from harlequin.catalog_lookup import CatalogLookup, OnLoaded
from harlequin.relations.candidates import join_candidates
from harlequin.relations.graph import RelationGraph, Route
from harlequin.relations.joins import JoinRefusal, plan_joins
from harlequin.relations.scope import BufferScope, read_scope
from harlequin.relations.spelling import DEFAULT_RESERVED, path_for, table_name
from harlequin.statements import StatementSpan


@dataclass(frozen=True)
class Edit:
    offset: int | None
    """Buffer offset to insert at; None inserts at the cursor."""
    text: str


@dataclass(frozen=True)
class JoinCandidate:
    route: Route
    source: str
    preview: str


class RelationsService:
    def __init__(self, on_loaded: OnLoaded) -> None:
        self._on_loaded = on_loaded
        self.graph = RelationGraph(())
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
        self, route: Route, statement: StatementSpan | None
    ) -> Edit | JoinRefusal:
        plan = plan_joins(
            route, _scope(statement), self.reserved, self.lookup.known_relations()
        )
        if isinstance(plan, JoinRefusal):
            return plan
        if plan.anchor is None or statement is None:
            prefix = "" if statement is None else "\n"
            return Edit(offset=None, text=prefix + plan.text)
        return Edit(offset=statement.start + plan.anchor, text=plan.text)

    def join_candidates(self, statement: StatementSpan | None) -> list[JoinCandidate]:
        scope = _scope(statement)
        known = self.lookup.known_relations()
        candidates: list[JoinCandidate] = []
        for route in join_candidates(scope, self.graph, known):
            plan = plan_joins(route, scope, self.reserved, known)
            preview = (
                plan.reason
                if isinstance(plan, JoinRefusal)
                else "\n".join(line.strip() for line in plan.text.splitlines() if line.strip())
            )
            source = scope.reference_for(route.source, known) or table_name(route.source)
            candidates.append(JoinCandidate(route=route, source=source, preview=preview))
        return candidates


def _scope(statement: StatementSpan | None) -> BufferScope:
    return read_scope(statement.text) if statement is not None else BufferScope()
```

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_service.py -q -n0 -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 4: Перевести `app.py` на сервис**

1. Импорты: убрать `read_scope`, `path_for`, `statement_at` (если больше не используется), добавить:

```python
from harlequin.relations_service import Edit, RelationsService
from harlequin.statements import StatementSpan, statement_span_at
```

2. В `__init__` рядом с `self.catalog: Catalog | None = None` заменить `self.reserved_words: frozenset[str] = DEFAULT_RESERVED` на:

```python
        self.relations = RelationsService(
            on_loaded=lambda parent, items: self.post_message(
                NewCatalogItems(parent=parent, items=items)
            )
        )
```

3. `handle_new_catalog`: после `self.catalog = message.catalog` добавить `self.relations.update_catalog(message.catalog)`.

4. Обработчик `CompletersReady` (там, где сейчас `self.reserved_words = message.reserved_words`): заменить на `self.relations.reserved = message.reserved_words`.

5. `update_relations_panel`:

```python
    @on(RelationsReady)
    def update_relations_panel(self, message: RelationsReady) -> None:
        self.relations.graph = message.graph
        self.relations_panel.update_graph(message.graph)
```

6. Хелперы statement вместо `_scope_text`:

```python
    def _statement(self) -> StatementSpan | None:
        assert self.editor is not None
        return statement_span_at(self.editor.text, self.editor.selection.end)

    def _statement_text(self) -> str:
        assert self.editor is not None
        span = self._statement()
        return span.text if span is not None else self.editor.text
```

7. `_insert_text_for`: заменить вызов `path_for(...)` на

```python
        return self.relations.path_for_item(
            node.data,
            owner if isinstance(owner, CatalogItem) else None,
            self._statement_text(),
        )
```

8. Ветка отфильтрованного дерева в `insert_node_into_editor`:

```python
            self.resolve_and_insert_path(
                node.data.qualified_identifier,
                _database_of(node),
                self._statement_text(),
            )
```

9. `insert_relation_path` и `resolve_and_insert_path`:

```python
    @on(RelationsPanel.PathRequested)
    def insert_relation_path(self, message: RelationsPanel.PathRequested) -> None:
        if self.editor is None:
            self._recycle_message(message)
            return
        self.resolve_and_insert_path(
            message.qualified_identifier, message.database, self._statement_text()
        )

    @work(thread=True, exclusive=True, exit_on_error=False, group="relation_paths")
    def resolve_and_insert_path(
        self, qualified_identifier: str, database: str | None, statement: str
    ) -> None:
        """Resolve off the event loop: finding the item may query the database."""
        text = self.relations.path_text(qualified_identifier, database, statement)
        if text is None:
            self.notify(
                f"{qualified_identifier} is not in the catalog.", severity="warning"
            )
            return
        self.post_message(HarlequinDriver.InsertTextAtSelection(text=text))
```

10. Удалить `_scope_text`, `_known_relations`, `_find_catalog_item`, `_children_of`. Проверить: `grep -n "_scope_text\|_known_relations\|_find_catalog_item\|_children_of\|reserved_words" src/harlequin/app.py` — остаются только `reserved_words=` в `CompletersReady(...)` и в его конструкторе.

11. Добавить применение правки (нужно в Task 7, но место ему здесь, рядом с хелперами):

```python
    def _apply_edit(self, edit: Edit) -> None:
        assert self.editor is not None and self.editor.text_input is not None
        if edit.offset is None:
            self.editor.insert_text_at_selection(text=edit.text)
        else:
            text_area = self.editor.text_input
            location = text_area.document.get_location_from_index(edit.offset)
            text_area.move_cursor(text_area.insert(edit.text, location).end_location)
        self.editor.focus()
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_relations_service.py tests/unit_tests/test_references.py tests/functional_tests/test_data_catalog.py tests/functional_tests/test_app.py -q -p no:cacheprovider`
Expected: PASS (поведение вставки из каталога и фильтра не изменилось). Затем ruff и mypy.

- [ ] **Step 6: Commit**

```bash
git add src/harlequin/catalog_lookup.py src/harlequin/relations_service.py src/harlequin/app.py tests/unit_tests/test_relations_service.py
git commit -m "refactor: move catalog lookup and path insertion out of the app"
```

---

### Task 6: Новая панель связей

**Files:**
- Rewrite: `src/harlequin/components/relations_panel.py`
- Modify: `src/harlequin/app.py` (обработчики `InsertPath`, `InsertJoin`, `_insert_join`)
- Modify: `src/harlequin/app.tcss` (блок `RelationsPanel`)
- Test: `tests/functional_tests/test_relations.py` (новый)

**Interfaces:**
- Consumes: `RelationGraph`, `Link`, `Route` (Task 2); `table_name` (Task 4); `RelationsService.join_edit`, `Harlequin._apply_edit`, `_statement`, `_statement_text` (Task 5).
- Produces:
  - `RelationsPanel(Vertical)`: `update_graph(graph)`, `show(identifier | None, database=None)`, свойства `trail -> tuple[str, ...]`, `rows -> OptionList`, `fields -> OptionList`
  - сообщения `RelationsPanel.InsertPath(identifier, database)`, `RelationsPanel.InsertJoin(route, database)`
  - `route_label(route: Route, source: str | None = None, emphasize: bool = False) -> Text` (использует пикер)
  - `Harlequin._insert_join(route: Route | None) -> None`

- [ ] **Step 1: Функциональные тесты панели**

`tests/functional_tests/test_relations.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

import duckdb
import pytest
from textual.widgets.text_area import Selection

from harlequin import Harlequin
from harlequin.adapter import HarlequinAdapter
from harlequin.app import RelationsReady
from harlequin.catalog import ForeignKeyEdge
from harlequin.components.code_editor import CodeEditor
from harlequin.relations.graph import RelationGraph
from tests.functional_tests.helpers import wait_for_catalog_tree, wait_for_editor
from tests.waiting import wait_for

SHOP_SQL = """
create table customer(customerid int primary key, name varchar);
create table orders(orderid int primary key, customerid int references customer(customerid));
create table orderline(orderid int references orders(orderid), qty int);
"""


def shop(name: str) -> str:
    return f'"shop"."main"."{name}"'


def shop_edge(
    src: str, column: str, dst: str, nullable: bool = False
) -> ForeignKeyEdge:
    return ForeignKeyEdge(
        constraint_name=f"{src}_{dst}",
        from_relation=shop(src),
        from_columns=(column,),
        to_relation=shop(dst),
        to_columns=(column,),
        database="shop",
        nullable=nullable,
    )


SHOP_GRAPH = RelationGraph(
    [
        shop_edge("orders", "customerid", "customer", nullable=True),
        shop_edge("orderline", "orderid", "orders"),
    ]
)


@pytest.fixture
def app_shop(duckdb_adapter: type[HarlequinAdapter], tmp_path: Path) -> Harlequin:
    path = tmp_path / "shop.db"
    conn = duckdb.connect(str(path))
    conn.execute(SHOP_SQL)
    conn.close()
    return Harlequin(duckdb_adapter([str(path)], no_init=True), connection_hash="shop")


async def ready(
    pilot, app: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> CodeEditor:
    await wait_for_workers(app)
    editor = await wait_for_editor(pilot, app)
    await wait_for_catalog_tree(pilot, app)
    app.post_message(RelationsReady(graph=SHOP_GRAPH))
    await pilot.pause()
    return editor


def put(editor: CodeEditor, text: str, cursor: tuple[int, int]) -> None:
    editor.text = text
    editor.selection = Selection(cursor, cursor)


def row_texts(app: Harlequin) -> list[str]:
    rows = app.relations_panel.rows
    return [str(rows.get_option_at_index(i).prompt) for i in range(rows.option_count)]


@pytest.mark.asyncio
async def test_a_column_raises_its_own_link(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await ready(pilot, app_shop, wait_for_workers)
        panel = app_shop.relations_panel

        panel.show(shop("orders"), "shop")
        await pilot.pause()
        assert "customer" in row_texts(app_shop)[0]

        panel.show(f'{shop("orders")}."orderid"', "shop")
        await pilot.pause()
        assert "orderline" in row_texts(app_shop)[0]
        assert panel.trail == ("orders",)


@pytest.mark.asyncio
async def test_l_and_h_walk_the_links(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await ready(pilot, app_shop, wait_for_workers)
        panel = app_shop.relations_panel
        panel.show(shop("orders"), "shop")
        panel.rows.focus()
        await pilot.pause()

        await pilot.press("l")
        assert panel.trail == ("orders", "customer")
        await pilot.press("h")
        assert panel.trail == ("orders",)


@pytest.mark.asyncio
async def test_a_new_graph_drops_the_walked_path(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        await ready(pilot, app_shop, wait_for_workers)
        panel = app_shop.relations_panel
        panel.show(shop("orders"), "shop")
        panel.rows.focus()
        await pilot.press("l")

        app_shop.post_message(RelationsReady(graph=SHOP_GRAPH))
        await pilot.pause()
        assert panel.trail == ("orders",)


@pytest.mark.asyncio
async def test_enter_inserts_the_table_under_its_alias(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select * from main.customer cu where ", (0, 37))
        panel = app_shop.relations_panel
        panel.show(shop("orders"), "shop")
        panel.rows.focus()
        await pilot.pause()

        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: editor.text == "select * from main.customer cu where cu",
            description="the customer alias to be inserted",
        )


@pytest.mark.asyncio
async def test_tab_then_enter_inserts_a_field(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select  from main.orders o", (0, 7))
        panel = app_shop.relations_panel
        panel.show(shop("orders"), "shop")
        panel.rows.focus()
        await pilot.pause()

        await pilot.press("tab", "enter")
        await wait_for(
            pilot,
            lambda: editor.text == "select o.customerid from main.orders o",
            description="the near field to be inserted",
        )


@pytest.mark.asyncio
async def test_shift_j_inserts_a_join_under_the_last_one(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select *\nfrom main.orders o\nwhere true", (0, 0))
        panel = app_shop.relations_panel
        panel.show(shop("orders"), "shop")
        panel.rows.focus()
        await pilot.pause()

        await pilot.press("J")
        await pilot.pause()
        assert editor.text == (
            "select *\nfrom main.orders o\n"
            "left join main.customer c on c.customerid = o.customerid\nwhere true"
        )
```

Run: `.venv/bin/python -m pytest tests/functional_tests/test_relations.py -q -n0 -p no:cacheprovider`
Expected: FAIL — у панели нет `rows`, `trail`.

- [ ] **Step 2: Переписать `relations_panel.py`**

```python
"""Foreign keys around the catalog item under the cursor."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from harlequin.relations.graph import Link, RelationGraph, Route
from harlequin.relations.spelling import table_name

DIM = Style(dim=True)
BOLD = Style(bold=True)
NAME_WIDTH = 18


def route_label(
    route: Route, source: str | None = None, emphasize: bool = False
) -> Text:
    if len(route) > 1:
        via = table_name(route.steps[0].far_relation)
        return Text.assemble(
            ("⋯ ", DIM),
            f"{table_name(route.target):<{NAME_WIDTH}}",
            (f" {len(route)} шага via {via}", DIM),
        )
    link = route.steps[0]
    arrow = "→" if link.direction == "out" else "←"
    mark = "?" if link.nullable else " "
    columns = ", ".join(link.near_columns)
    return Text.assemble(
        (f"{arrow} ", BOLD),
        (f"{table_name(link.far_relation):<{NAME_WIDTH}}", BOLD if emphasize else ""),
        (f" {link.cardinality}{mark} ", DIM),
        f"{source}.{columns}" if source else columns,
    )


class RelationsPanel(Vertical):
    BORDER_TITLE = "Relations"

    BINDINGS = [
        Binding("j", "move(1)", "Down", show=False),
        Binding("k", "move(-1)", "Up", show=False),
        Binding("l", "step_in", "Step In", show=False),
        Binding("h", "step_out", "Step Out", show=False),
        Binding("tab", "switch_list", "Fields", show=False),
        Binding("J", "insert_join", "Insert Join", show=True),
        Binding("f", "toggle_routes", "Toggle Routes", show=False),
    ]

    class InsertPath(Message):
        def __init__(self, identifier: str, database: str | None) -> None:
            super().__init__()
            self.identifier = identifier
            self.database = database

    class InsertJoin(Message):
        def __init__(self, route: Route, database: str | None) -> None:
            super().__init__()
            self.route = route
            self.database = database

    def __init__(self) -> None:
        super().__init__(id="relations_panel")
        self.graph = RelationGraph(())
        self.show_routes = True
        self._root: str | None = None
        self._column: str | None = None
        self._database: str | None = None
        self._path: tuple[Link, ...] = ()
        self._routes: list[Route] = []

    def compose(self) -> ComposeResult:
        yield Static(id="relation_crumbs")
        yield OptionList(id="relation_rows")
        yield OptionList(id="relation_fields")
        yield Static(id="relation_hint")

    def on_mount(self) -> None:
        self._render()

    @property
    def rows(self) -> OptionList:
        return self.query_one("#relation_rows", OptionList)

    @property
    def fields(self) -> OptionList:
        return self.query_one("#relation_fields", OptionList)

    @property
    def trail(self) -> tuple[str, ...]:
        if self._root is None:
            return ()
        return tuple(
            table_name(relation)
            for relation in (self._root, *(link.far_relation for link in self._path))
        )

    def update_graph(self, graph: RelationGraph) -> None:
        self.graph = graph
        self._path = ()
        self._render()

    def show(self, identifier: str | None, database: str | None = None) -> None:
        found = self.graph.relation_of(identifier) if identifier else None
        self._root, self._column = found if found is not None else (None, None)
        self._database = database
        self._path = ()
        self._render()

    def action_move(self, delta: int) -> None:
        target = self.fields if self.fields.has_focus else self.rows
        if delta > 0:
            target.action_cursor_down()
        else:
            target.action_cursor_up()

    def action_step_in(self) -> None:
        route = self._route_at(self.rows.highlighted)
        if route is not None:
            self._path += route.steps
            self._render()

    def action_step_out(self) -> None:
        if self._path:
            self._path = self._path[:-1]
            self._render()

    def action_switch_list(self) -> None:
        (self.rows if self.fields.has_focus else self.fields).focus()

    def action_insert_join(self) -> None:
        route = self._route_at(self.rows.highlighted)
        if route is not None:
            self.post_message(
                self.InsertJoin(Route(self._path + route.steps), self._database)
            )

    def action_toggle_routes(self) -> None:
        self.show_routes = not self.show_routes
        self._render()

    @on(OptionList.OptionHighlighted, "#relation_rows")
    def _row_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._show_details(self._route_at(event.option_index))

    @on(OptionList.OptionSelected, "#relation_rows")
    def _row_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        route = self._route_at(event.option_index)
        if route is not None:
            self.post_message(self.InsertPath(route.target, self._database))

    @on(OptionList.OptionSelected, "#relation_fields")
    def _field_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id is not None:
            self.post_message(self.InsertPath(event.option.id, self._database))

    def _render(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#relation_crumbs", Static).update(" › ".join(self.trail))
        rows = self.rows
        rows.clear_options()
        self._routes = []
        current = self._path[-1].far_relation if self._path else self._root
        if not self.graph or not self.graph.covers(self._database):
            self._note("нет внешних ключей")
        elif current is None:
            self._note("выбери таблицу или поле")
        else:
            self._routes = self._routes_from(current)
            if self._routes:
                rows.add_options(
                    Option(route_label(route, emphasize=self._emphasized(route)))
                    for route in self._routes
                )
                rows.highlighted = 0
            else:
                self._note("связей нет")
        self._show_details(self._route_at(0))

    def _routes_from(self, relation: str) -> list[Route]:
        links = self.graph.links_for(relation)
        if self._column is not None and not self._path:
            links.sort(key=lambda link: self._column not in link.near_columns)
        routes = [Route((link,)) for link in links]
        if self.show_routes:
            routes += sorted(
                self.graph.routes_from(relation),
                key=lambda route: (len(route), route.target),
            )
        return routes

    def _emphasized(self, route: Route) -> bool:
        return (
            not self._path
            and len(route) == 1
            and self._column in route.steps[0].near_columns
        )

    def _show_details(self, route: Route | None) -> None:
        fields = self.fields
        fields.clear_options()
        hint = self.query_one("#relation_hint", Static)
        if route is None:
            hint.update("")
            return
        if len(route) > 1:
            hint.update(
                Text(" › ".join(table_name(s.far_relation) for s in route.steps), DIM)
            )
            return
        link = route.steps[0]
        near, far = table_name(link.near_relation), table_name(link.far_relation)
        for near_column, far_column in zip(link.near_columns, link.far_columns):
            fields.add_option(
                Option(
                    f"on {near}.{near_column} =",
                    id=f'{link.near_relation}."{near_column}"',
                )
            )
            fields.add_option(
                Option(f"   {far}.{far_column}", id=f'{link.far_relation}."{far_column}"')
            )
        fields.highlighted = 0
        hint.update(Text("nullable → left join", DIM) if link.nullable else "")

    def _route_at(self, index: int | None) -> Route | None:
        if index is None or not 0 <= index < len(self._routes):
            return None
        return self._routes[index]

    def _note(self, message: str) -> None:
        self.rows.add_option(Option(Text(message, DIM), disabled=True))
```

- [ ] **Step 3: Обработчики в `app.py`**

Заменить старый обработчик `insert_relation_path` (`@on(RelationsPanel.PathRequested)`) на:

```python
    @on(RelationsPanel.InsertPath)
    def insert_relation_path(self, message: RelationsPanel.InsertPath) -> None:
        message.stop()
        if self.editor is None:
            self._recycle_message(message)
            return
        self.resolve_and_insert_path(
            message.identifier, message.database, self._statement_text()
        )

    @on(RelationsPanel.InsertJoin)
    def insert_relation_join(self, message: RelationsPanel.InsertJoin) -> None:
        message.stop()
        self._insert_join(message.route)

    def _insert_join(self, route: Route | None) -> None:
        if route is None or self.editor is None:
            return
        edit = self.relations.join_edit(route, self._statement())
        if isinstance(edit, JoinRefusal):
            self.notify(edit.reason, severity="warning")
            return
        self._apply_edit(edit)
```

Импорты: `from harlequin.relations.graph import RelationGraph, Route`, `from harlequin.relations.joins import JoinRefusal`.

`show_relations_for_node` не меняется: он уже вызывает `self.relations_panel.show(identifier, database)`. Удалить из него проверку `message.control is not self.data_catalog.database_tree`? Нет — оставить: `FilteredTree` тоже `HarlequinTree`, а панель по нему не обновляется, как и раньше. Трёхстрочный комментарий над проверкой сократить до одной строки: `# the filtered tree highlights too, and the panel follows only the real one`.

- [ ] **Step 4: Стили**

В `src/harlequin/app.tcss` заменить блок `RelationsPanel { ... }` (вместе с комментарием над ним) на:

```css
RelationsPanel {
    height: 16;
    background: $background;
    padding: 0 1;
    border: round $border-color-nofocus;
    &:focus-within {
        border: round $border-color-focus;
    }
}

RelationsPanel #relation_crumbs {
    height: 1;
    color: $foreground 60%;
}

RelationsPanel OptionList {
    border: none;
    padding: 0;
    background: $background;
}

RelationsPanel #relation_rows {
    height: 1fr;
}

RelationsPanel #relation_fields {
    height: auto;
    max-height: 4;
    border-top: solid $panel;
}

RelationsPanel #relation_hint {
    height: auto;
}
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/functional_tests/test_relations.py tests/functional_tests/test_data_catalog.py tests/functional_tests/test_layout.py -q -p no:cacheprovider`
Expected: PASS. Если снапшоты `test_layout` падают из-за новой панели — посмотреть отчёт (`snapshot_report.html`), убедиться, что изменилась только панель, и обновить: `--snapshot-update` для этих тестов.

- [ ] **Step 6: Commit**

```bash
git add src/harlequin/components/relations_panel.py src/harlequin/app.py src/harlequin/app.tcss tests/functional_tests/test_relations.py tests/functional_tests/__snapshots__
git commit -m "feat: rebuild the Relations panel as a walkable list of links"
```

`app.tcss` содержит чужой незакоммиченный блок `:ansi`. Перед `git add` проверить `git diff src/harlequin/app.tcss`: если там есть чужие строки, добавлять интерактивно нельзя (`-i`/`-p` не поддерживаются) — оставить `app.tcss` вне коммита и сообщить пользователю.

---

### Task 7: JOIN-пикер

**Files:**
- Create: `src/harlequin/components/join_picker.py`
- Modify: `src/harlequin/components/code_editor.py` (`action_show_join_picker`)
- Modify: `src/harlequin/actions.py` (регистрация действия)
- Modify: `src/harlequin_vimnav/__init__.py` (бинд `ctrl+l`)
- Modify: `src/harlequin/app.py` (`action_show_join_picker`)
- Modify: `src/harlequin/app.tcss` (стили пикера)
- Test: `tests/functional_tests/test_relations.py` (дописать)

**Interfaces:**
- Consumes: `JoinCandidate`, `RelationsService.join_candidates` (Task 5); `route_label` (Task 6); `Harlequin._insert_join` (Task 6).
- Produces: `JoinPicker(ModalScreen[Union[Route, None]])(candidates: Sequence[JoinCandidate], empty_message: str)`; `Harlequin.action_show_join_picker()`; действие `code_editor.show_join_picker`.

- [ ] **Step 1: Тесты пикера**

Дописать в `tests/functional_tests/test_relations.py`:

```python
from textual.widgets import OptionList

from harlequin.components.join_picker import JoinPicker


@pytest.mark.asyncio
async def test_picker_filters_and_inserts_a_chain(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select *\nfrom main.customer c", (1, 5))

        app_shop.action_show_join_picker()
        await pilot.pause()
        assert isinstance(app_shop.screen, JoinPicker)

        await pilot.press("l", "i", "n", "e")
        options = app_shop.screen.query_one("#join_candidates", OptionList)
        assert options.option_count == 1
        await pilot.press("enter")
        await pilot.pause()

        assert editor.text == (
            "select *\nfrom main.customer c"
            "\njoin main.orders o on o.customerid = c.customerid"
            "\njoin main.orderline o2 on o2.orderid = o.orderid"
        )


@pytest.mark.asyncio
async def test_picker_escape_changes_nothing(
    app_shop: Harlequin, wait_for_workers: Callable[[Harlequin], Awaitable[None]]
) -> None:
    async with app_shop.run_test(size=(140, 40)) as pilot:
        editor = await ready(pilot, app_shop, wait_for_workers)
        put(editor, "select * from main.customer c", (0, 3))

        app_shop.action_show_join_picker()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app_shop.screen, JoinPicker)
        assert editor.text == "select * from main.customer c"
```

Импорты `OptionList` и `JoinPicker` перенести наверх файла к остальным импортам.

И в `tests/functional_tests/test_keymap_vimnav.py` дописать проверку бинда (поля `HarlequinKeyBinding` — `keys` и `action`):

```python
def test_vimnav_binds_the_join_picker() -> None:
    from harlequin_vimnav import VIMNAV_EDITOR_BINDINGS

    assert any(
        binding.keys == "ctrl+l" and binding.action == "code_editor.show_join_picker"
        for binding in VIMNAV_EDITOR_BINDINGS
    )
```

Run: `.venv/bin/python -m pytest tests/functional_tests/test_relations.py tests/functional_tests/test_keymap_vimnav.py -q -n0 -p no:cacheprovider`
Expected: FAIL — нет `join_picker`.

- [ ] **Step 2: `join_picker.py`**

```python
"""Pick a table to join to the statement under the cursor."""

from __future__ import annotations

from typing import Sequence, Union

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from harlequin.components.relations_panel import route_label
from harlequin.relations.graph import Route
from harlequin.relations.spelling import table_name
from harlequin.relations_service import JoinCandidate


class JoinPicker(ModalScreen[Union[Route, None]]):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
    ]

    def __init__(
        self, candidates: Sequence[JoinCandidate], empty_message: str
    ) -> None:
        super().__init__()
        self._all = list(candidates)
        self._shown = list(candidates)
        self._empty_message = empty_message

    def compose(self) -> ComposeResult:
        with Vertical(id="join_picker"):
            yield Input(placeholder="фильтр", id="join_filter")
            yield OptionList(id="join_candidates")
            yield Static(id="join_preview")

    def on_mount(self) -> None:
        self.query_one("#join_picker").border_title = "Join"
        self._refill()
        self.query_one(Input).focus()

    @on(Input.Changed)
    def _filter(self, event: Input.Changed) -> None:
        term = event.value.casefold()
        self._shown = [
            candidate
            for candidate in self._all
            if term in table_name(candidate.route.target).casefold()
        ]
        self._refill()

    @on(OptionList.OptionHighlighted)
    def _preview(self, event: OptionList.OptionHighlighted) -> None:
        if 0 <= event.option_index < len(self._shown):
            self.query_one("#join_preview", Static).update(
                self._shown[event.option_index].preview
            )

    @on(Input.Submitted)
    def _submit(self) -> None:
        self._choose(self.query_one(OptionList).highlighted)

    @on(OptionList.OptionSelected)
    def _select(self, event: OptionList.OptionSelected) -> None:
        self._choose(event.option_index)

    def action_move(self, delta: int) -> None:
        options = self.query_one(OptionList)
        if delta > 0:
            options.action_cursor_down()
        else:
            options.action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _choose(self, index: int | None) -> None:
        if index is not None and 0 <= index < len(self._shown):
            self.dismiss(self._shown[index].route)

    def _refill(self) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        preview = self.query_one("#join_preview", Static)
        if not self._shown:
            message = self._empty_message if not self._all else "ничего не найдено"
            options.add_option(Option(Text(message, style="dim"), disabled=True))
            preview.update("")
            return
        options.add_options(
            Option(route_label(candidate.route, source=candidate.source))
            for candidate in self._shown
        )
        options.highlighted = 0
```

- [ ] **Step 3: Действие и бинд**

`src/harlequin/components/code_editor.py`, рядом с `action_focus_data_catalog`:

```python
    def action_show_join_picker(self) -> None:
        if hasattr(self.app, "action_show_join_picker"):
            self.app.action_show_join_picker()
```

`src/harlequin/actions.py`, после `"code_editor.focus_data_catalog"`:

```python
    "code_editor.show_join_picker": Action(
        target=CodeEditor,
        action="show_join_picker",
        description="Join Table",
        show=True,
    ),
```

`src/harlequin_vimnav/__init__.py`, в `VIMNAV_EDITOR_BINDINGS`:

```python
    HarlequinKeyBinding("ctrl+l", "code_editor.show_join_picker"),
```

`src/harlequin/app.py`:

```python
    def action_show_join_picker(self) -> None:
        if self.editor is None:
            return
        empty = "нечего присоединять" if self.relations.graph else "нет внешних ключей"
        self.push_screen(
            JoinPicker(self.relations.join_candidates(self._statement()), empty),
            callback=self._insert_join,
        )
```

Импорт: `from harlequin.components.join_picker import JoinPicker`.

- [ ] **Step 4: Стили пикера**

В `src/harlequin/app.tcss`:

```css
JoinPicker {
    align: center middle;
}

#join_picker {
    width: 64;
    height: auto;
    max-height: 26;
    padding: 0 1;
    background: $background;
    border: round $border-color-focus;
}

#join_picker Input {
    border: none;
    height: 1;
}

#join_candidates {
    height: auto;
    max-height: 14;
    border: none;
    background: $background;
}

#join_preview {
    height: auto;
    border-top: solid $panel;
}
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/functional_tests/test_relations.py tests/functional_tests/test_keymap_vimnav.py tests/functional_tests/test_help_screen.py -q -p no:cacheprovider`
Expected: PASS. Если снапшот help-экрана поменялся из-за нового действия с `show=True` — проверить отчёт и обновить `--snapshot-update`.

- [ ] **Step 6: Полный прогон**

Run: `.venv/bin/python -m pytest tests -q -p no:cacheprovider`
Expected: падают только тесты из списка базовых падений в Global Constraints. Затем `ruff check`, `ruff format --check`, `mypy src/harlequin`.

- [ ] **Step 7: Commit**

```bash
git add src/harlequin/components/join_picker.py src/harlequin/components/code_editor.py src/harlequin/actions.py src/harlequin_vimnav/__init__.py src/harlequin/app.py tests/functional_tests/test_relations.py tests/functional_tests/test_keymap_vimnav.py tests/functional_tests/__snapshots__
git commit -m "feat: pick a join from the tables the query can reach"
```

(то же правило про `app.tcss`, что в Task 6).

---

### Task 8: Ручная проверка на `retail_training`

**Files:** нет изменений.

- [ ] **Step 1: Запуск**

```bash
cd ~/itmo/02-databases/sql-course && ./bin/db up
cd ~/src/harlequin && .venv/bin/harlequin -a pgfk "host=localhost dbname=retail_training" --keymap-name vscode --keymap-name vimnav
```

- [ ] **Step 2: Сценарии**

1. В каталоге курсор на `sales.customer`: в панели `→ person  N:1? personid` и `← salesorderheader  1:N  customerid`, в футере `on customer.personid =` / `person.personid` и «nullable → left join».
2. Курсор на `sales.salesorderdetail.productid`: первая строка — `→ product`, выделена.
3. В панели `l` на `product`, крошки `salesorderdetail › product`; `h` возвращает.
4. Буфер `select * from sales.salesorderdetail sod`, в панели на `salesorderdetail` жмём `J` на строке `→ product` → под `from` появилась `join production.product p on p.productid = sod.productid`.
5. В редакторе `ctrl+l`, фильтр `store`, `Enter` → вставилась цепочка до `sales.store` через промежуточные таблицы, без дублей уже присоединённых.
6. Пустой буфер, `ctrl+l`, выбрать кандидата → «нечего присоединять»; в панели на `customer` `J` → вставился `from sales.customer c` + join.

Результаты (что сработало, что нет) — сообщить пользователю перед закрытием работы.
