# Разрешение путей и алиасов — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** вставка элемента каталога в редактор кладёт пригодный к работе путь до поля — через алиас, если таблица в буфере под алиасом, иначе полный, — вместо голого имени в кавычках.

**Architecture:** новый модуль `harlequin/references.py` читает текущий буфер одним проходом tree-sitter и отвечает на вопрос «под каким именем эта таблица доступна прямо сейчас». Функция `path_for()` собирает из элемента каталога, его владельца и этого ответа строку для вставки. Обработчик `insert_node_into_editor` в `app.py` начинает звать `path_for()` вместо `message.insert_name`.

**Tech Stack:** Python 3.9+, textual 8.2.8, tree-sitter через `harlequin.statements`, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-20-harlequin-fork-design.md`, раздел 1.

## Global Constraints

- Ветка `maksibon-fork`, база — upstream `v2.15.0`.
- Ничего адаптеро-специфичного в ядре: правила работают через `CatalogItem.query_name` и `qualified_identifier`, а не через знание о постгресе.
- Модуль импортируется из ядра, поэтому tree-sitter подтягивается отложенным импортом внутри функции — как это уже сделано в `autocomplete/symbols.py:58`.
- Стиль кода: `from __future__ import annotations` первой строкой, полные аннотации типов, докстроки объясняют «почему», а не «что».
- Проверка перед коммитом: `pytest tests/unit_tests/test_references.py -v` и `ruff check src/harlequin`.

---

### Task 1: Чтение алиасов из буфера

**Files:**
- Create: `src/harlequin/references.py`
- Modify: `src/harlequin/navigate.py:177` (переименовать `_split` в `split_path`, обновить вызовы внутри файла)
- Test: `tests/unit_tests/test_references.py`

**Interfaces:**
- Consumes: `harlequin.statements.captures(text, pattern) -> dict[str, list[Node]]`; `harlequin.navigate.split_path(text) -> list[tuple[str, bool]]`.
- Produces: `RelationRef(name: str, alias: str | None, is_cte: bool)`; `BufferScope(relations: tuple[RelationRef, ...])` с методом `alias_for(qualified_identifier: str) -> str | None`; `read_scope(text: str) -> BufferScope`.

**Почему обход детей, а не парные капчуры:** `captures()` возвращает независимые списки на каждое имя капчура, и порядок в них не совпадает. Запрос `(relation (object_reference) @obj (identifier) @alias)` на буфере из четырёх таблиц ставит `person.person` напротив алиаса `c`. Пары собираются обходом детей узла `(relation)`.

- [ ] **Step 1: Сделать `split_path` публичной**

В `src/harlequin/navigate.py` переименовать `def _split(` в `def split_path(` и заменить оба вызова `_split(` на `split_path(` внутри файла (в `CatalogPath.parse`). Больше нигде в проекте `_split` не используется — проверить: `grep -rn "_split" src/`.

- [ ] **Step 2: Убедиться, что существующие тесты навигации не сломались**

Run: `pytest tests/unit_tests -k navigate -v`
Expected: PASS

- [ ] **Step 3: Написать падающий тест на чтение алиасов**

Создать `tests/unit_tests/test_references.py`:

```python
from __future__ import annotations

import pytest

from harlequin.references import BufferScope, RelationRef, read_scope


def test_read_scope_finds_aliases_and_bare_relations() -> None:
    sql = """
        with recent as (select * from sales.salesorderheader)
        select c.customerid
        from recent r
        join sales.customer c on r.customerid = c.customerid
        join person.person as p on c.personid = p.personid
        join sales.store on 1 = 1
    """

    scope = read_scope(sql)

    assert scope.relations == (
        RelationRef(name="sales.salesorderheader", alias=None, is_cte=False),
        RelationRef(name="recent", alias="r", is_cte=True),
        RelationRef(name="sales.customer", alias="c", is_cte=False),
        RelationRef(name="person.person", alias="p", is_cte=False),
        RelationRef(name="sales.store", alias=None, is_cte=False),
    )


def test_read_scope_survives_a_broken_buffer() -> None:
    scope = read_scope("select from sales.customer c join")

    assert RelationRef(name="sales.customer", alias="c", is_cte=False) in scope.relations


def test_read_scope_of_empty_text_is_empty() -> None:
    assert read_scope("   ") == BufferScope()
```

- [ ] **Step 4: Запустить тест и убедиться, что он падает**

Run: `pytest tests/unit_tests/test_references.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'harlequin.references'`

- [ ] **Step 5: Написать модуль**

Создать `src/harlequin/references.py`:

```python
"""What the current buffer calls the things in the catalog.

Inserting a name is only useful if the query can use it: a table written under
an alias has to be reached through that alias, because naming it in full is an
error once it is aliased. So every insertion asks this module what the buffer
already says about the item's table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node

RELATION_QUERY = "(relation) @relation"
"""Every table named in a FROM or JOIN, with whatever follows it as an alias."""

CTE_QUERY = "(cte (identifier) @name) @cte"
"""The names a WITH clause introduces, which no catalog item ever matches."""


@dataclass(frozen=True)
class RelationRef:
    """One table as the buffer writes it."""

    name: str
    """The relation as written, e.g. "sales.customer". Not normalized."""

    alias: str | None
    is_cte: bool


@dataclass(frozen=True)
class BufferScope:
    """The relations a buffer names, in the order they first appear."""

    relations: tuple[RelationRef, ...] = field(default=())

    def alias_for(self, qualified_identifier: str) -> str | None:
        """The alias under which `qualified_identifier` is available, if one is.

        A written reference matches an item when its segments equal the item's
        last segments: `sales.customer` reaches
        `"retail_training"."sales"."customer"`. If more than one reference
        matches -- two bare `customer`s from different schemas -- there is no
        answer, and the caller falls back to the full path. Guessing here would
        produce a query that is wrong rather than merely verbose.
        """
        from harlequin.navigate import split_path

        target = [segment.casefold() for segment, _ in split_path(qualified_identifier)]
        found: list[str] = []
        for relation in self.relations:
            if relation.alias is None or relation.is_cte:
                continue
            written = [segment.casefold() for segment, _ in split_path(relation.name)]
            if written and written == target[-len(written) :]:
                found.append(relation.alias)
        return found[0] if len(found) == 1 else None


def read_scope(text: str) -> BufferScope:
    """Read every relation the buffer names, with its alias where it has one."""
    if not text.strip():
        return BufferScope()

    # deferred: every adapter imports this package, and only an insertion into
    # the Query Editor ever parses SQL with it.
    from harlequin.statements import captures

    cte_names = {
        node.text.decode("utf-8").casefold()
        for node in captures(text, CTE_QUERY).get("name", [])
        if node.text is not None
    }

    relations: list[RelationRef] = []
    for node in sorted(
        captures(text, RELATION_QUERY).get("relation", []),
        key=lambda found: found.start_byte,
    ):
        name, alias = _name_and_alias(node)
        if not name:
            continue
        relations.append(
            RelationRef(name=name, alias=alias, is_cte=name.casefold() in cte_names)
        )
    return BufferScope(relations=tuple(relations))


def _name_and_alias(relation: Node) -> tuple[str, str | None]:
    """The table and its alias, read off the relation node's own children.

    Not from paired captures: `captures()` returns one list per capture name,
    and their orders do not line up, so the third table would be handed the
    second alias.
    """
    name = ""
    alias: str | None = None
    for child in relation.children:
        if child.text is None:
            continue
        if child.type == "object_reference":
            name = child.text.decode("utf-8")
        elif child.type == "identifier":
            alias = child.text.decode("utf-8")
    return name, alias
```

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `pytest tests/unit_tests/test_references.py -v`
Expected: PASS, три теста

- [ ] **Step 7: Добавить тесты на сопоставление с каталогом**

Дописать в `tests/unit_tests/test_references.py`:

```python
def test_alias_for_matches_by_suffix() -> None:
    scope = read_scope("select 1 from sales.customer c")

    assert scope.alias_for('"retail_training"."sales"."customer"') == "c"


def test_alias_for_matches_a_bare_name() -> None:
    scope = read_scope("select 1 from customer c")

    assert scope.alias_for('"retail_training"."sales"."customer"') == "c"


def test_alias_for_refuses_an_ambiguous_match() -> None:
    scope = read_scope("select 1 from customer c join customer d on 1 = 1")

    assert scope.alias_for('"retail_training"."sales"."customer"') is None


def test_alias_for_ignores_a_relation_without_an_alias() -> None:
    scope = read_scope("select 1 from sales.customer")

    assert scope.alias_for('"retail_training"."sales"."customer"') is None


def test_alias_for_ignores_a_cte_of_the_same_name() -> None:
    scope = read_scope(
        "with customer as (select 1) select 1 from customer c"
    )

    assert scope.alias_for('"retail_training"."sales"."customer"') is None


def test_alias_for_does_not_match_a_different_table() -> None:
    scope = read_scope("select 1 from sales.store s")

    assert scope.alias_for('"retail_training"."sales"."customer"') is None
```

- [ ] **Step 8: Запустить и убедиться, что проходят**

Run: `pytest tests/unit_tests/test_references.py -v`
Expected: PASS, девять тестов

- [ ] **Step 9: Проверить линтером**

Run: `ruff check src/harlequin/references.py src/harlequin/navigate.py`
Expected: без замечаний

- [ ] **Step 10: Коммит**

```bash
git add src/harlequin/references.py src/harlequin/navigate.py tests/unit_tests/test_references.py
git commit -m "feat: read the relations and aliases a buffer names"
```

---

### Task 2: Сборка пути для вставки

**Files:**
- Modify: `src/harlequin/references.py`
- Test: `tests/unit_tests/test_references.py`

**Interfaces:**
- Consumes: `BufferScope.alias_for()` из Task 1; `harlequin.catalog.CatalogItem` с полями `query_name` и `qualified_identifier`; `harlequin.autocomplete.constants.KEYWORDS: list[str]`.
- Produces: `path_for(item: CatalogItem, owner: CatalogItem | None, scope: BufferScope, reserved: frozenset[str]) -> str`; `DEFAULT_RESERVED: frozenset[str]`.

**Два правила, которые надо понять прежде чем читать код.**

Первое: как отличить колонку от таблицы, не зная адаптера. Адаптер сам отвечает на вопрос «что вставлять» полем `query_name`, и отвечает по-разному: у таблицы оно уже квалифицировано схемой (`"sales"."customer"`, два сегмента), у колонки — голое (`"customerid"`, один сегмент). Отсюда правило: **односегментное `query_name` дописывается к `query_name` владельца, многосегментное используется как есть.**

Второе: когда снимать кавычки. Сегмент остаётся голым, если он подходит под `^[a-z_][a-z0-9_]*$` и не зарезервирован. `"Order Date"`, `"Select"`, `"MixedCase"` кавычки сохраняют, потому что без них база прочитает их иначе или не прочитает вовсе.

- [ ] **Step 1: Написать падающие тесты на полный путь**

Дописать в `tests/unit_tests/test_references.py`:

```python
from harlequin.catalog import CatalogItem
from harlequin.references import DEFAULT_RESERVED, path_for


def _relation(schema: str, table: str) -> CatalogItem:
    return CatalogItem(
        qualified_identifier=f'"retail_training"."{schema}"."{table}"',
        query_name=f'"{schema}"."{table}"',
        label=table,
        type_label="t",
    )


def _column(schema: str, table: str, column: str) -> CatalogItem:
    return CatalogItem(
        qualified_identifier=f'"retail_training"."{schema}"."{table}"."{column}"',
        query_name=f'"{column}"',
        label=column,
        type_label="##",
    )


def test_path_for_column_without_the_table_in_the_buffer() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "sales.customer.customerid"


def test_path_for_column_uses_the_alias_when_there_is_one() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select from sales.customer c"),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "c.customerid"


def test_path_for_column_ignores_an_unaliased_table() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select from sales.customer"),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "sales.customer.customerid"


def test_path_for_relation_is_already_qualified() -> None:
    result = path_for(
        item=_relation("sales", "customer"),
        owner=None,
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "sales.customer"


def test_path_for_relation_collapses_to_its_alias() -> None:
    result = path_for(
        item=_relation("sales", "customer"),
        owner=None,
        scope=read_scope("select from sales.customer c"),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "c"


def test_path_for_keeps_quotes_around_an_unsafe_identifier() -> None:
    result = path_for(
        item=_column("sales", "customer", "Order Date"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == 'sales.customer."Order Date"'


def test_path_for_keeps_quotes_around_a_reserved_word() -> None:
    result = path_for(
        item=_column("sales", "customer", "order"),
        owner=_relation("sales", "customer"),
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == 'sales.customer."order"'


def test_path_for_without_an_owner_falls_back_to_the_query_name() -> None:
    result = path_for(
        item=_column("sales", "customer", "customerid"),
        owner=None,
        scope=read_scope("select "),
        reserved=DEFAULT_RESERVED,
    )

    assert result == "customerid"
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `pytest tests/unit_tests/test_references.py -v`
Expected: FAIL с `ImportError: cannot import name 'path_for'`

- [ ] **Step 3: Дописать модуль**

Добавить в `src/harlequin/references.py` — импорты в начало файла:

```python
import re

from harlequin.autocomplete.constants import KEYWORDS

if TYPE_CHECKING:
    from harlequin.catalog import CatalogItem
```

и в конец файла:

```python
UNQUOTED = re.compile(r"^[a-z_][a-z0-9_]*$")
"""An identifier a database reads the same whether or not it is quoted."""

DEFAULT_RESERVED: frozenset[str] = frozenset(KEYWORDS)
"""The words core knows are reserved, before an adapter says what it reserves."""


def path_for(
    item: "CatalogItem",
    owner: "CatalogItem | None",
    scope: BufferScope,
    reserved: frozenset[str],
) -> str:
    """The text to insert for `item`, usable in the query as it stands.

    An adapter spells `query_name` two ways: a relation's is already qualified
    by its schema, a column's is the bare column. So a single-segment name is
    the one that needs its owner in front of it, and that is what tells the two
    apart without core knowing which adapter it is talking to.
    """
    own_segments = _segments(item.query_name)
    if len(own_segments) > 1:
        alias = scope.alias_for(item.qualified_identifier)
        return alias if alias else _spell(own_segments, reserved)

    if owner is None:
        return _spell(own_segments, reserved)

    alias = scope.alias_for(owner.qualified_identifier)
    if alias:
        return f"{alias}.{_spell(own_segments, reserved)}"
    return _spell(_segments(owner.query_name) + own_segments, reserved)


def _segments(query_name: str) -> list[str]:
    from harlequin.navigate import split_path

    return [segment for segment, _ in split_path(query_name)]


def _spell(segments: list[str], reserved: frozenset[str]) -> str:
    return ".".join(_spell_segment(segment, reserved) for segment in segments)


def _spell_segment(segment: str, reserved: frozenset[str]) -> str:
    if UNQUOTED.match(segment) and segment not in reserved:
        return segment
    return '"' + segment.replace('"', '""') + '"'
```

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `pytest tests/unit_tests/test_references.py -v`
Expected: PASS, семнадцать тестов

- [ ] **Step 5: Проверить линтером и типами**

Run: `ruff check src/harlequin/references.py && mypy src/harlequin/references.py`
Expected: без замечаний

- [ ] **Step 6: Коммит**

```bash
git add src/harlequin/references.py tests/unit_tests/test_references.py
git commit -m "feat: build an insertable path from a catalog item and the buffer"
```

---

### Task 3: Подключение к вставке из дерева

**Files:**
- Modify: `src/harlequin/app.py:230` (поле в `CompletersReady`), `src/harlequin/app.py:581-590` (обработчик вставки), `src/harlequin/app.py:1066` (приём сообщения), `src/harlequin/app.py:1747` (сбор зарезервированных слов)
- Test: `tests/functional_tests/test_data_catalog.py`

**Interfaces:**
- Consumes: `path_for()`, `read_scope()`, `DEFAULT_RESERVED` из Task 2.
- Produces: `Harlequin.reserved_words: frozenset[str]` — слова, вокруг которых кавычки не снимаются; стартует как `DEFAULT_RESERVED` и расширяется словами адаптера.

**Важно:** дерево файлов и дерево S3 тоже шлют `NodeSubmitted`, и у их узлов в `data` лежит не `CatalogItem`, а `DirEntry` или строка. Для них поведение не меняется — вставляется прежний `message.insert_name`.

**Ожидаемая поломка существующего теста.** `test_double_click_inserts_node_into_editor` (строка 184) сейчас утверждает `editor.text == '"small"'` — это имя базы, вставленное в кавычках. После снятия кавычек оно станет `small`. Это намеренное изменение поведения, а не регрессия, и тест обновляется в шаге 6.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/functional_tests/test_data_catalog.py` после `test_double_click_inserts_node_into_editor`:

```python
@pytest.mark.asyncio
async def test_inserting_a_column_uses_its_alias(
    app_multi_duck: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_multi_duck
    async with app.run_test(size=(120, 36)) as pilot:
        await wait_for_workers(app)
        editor = await wait_for_editor(pilot, app)
        await wait_for_catalog_tree(pilot, app)

        # nodes of our own, so the test does not depend on the fixture's schema
        tree = app.data_catalog.database_tree
        table = tree.root.add(
            "customer",
            data=CatalogItem(
                qualified_identifier='"tiny"."main"."customer"',
                query_name='"main"."customer"',
                label="customer",
                type_label="t",
            ),
        )
        column = table.add_leaf(
            "customerid",
            data=CatalogItem(
                qualified_identifier='"tiny"."main"."customer"."customerid"',
                query_name='"customerid"',
                label="customerid",
                type_label="##",
            ),
        )

        editor.text = "select \nfrom main.customer c"
        tree.post_message(DatabaseTree.NodeSubmitted(node=column))
        await pilot.pause()

        assert "c.customerid" in editor.text

        editor.text = "select "
        tree.post_message(DatabaseTree.NodeSubmitted(node=column))
        await pilot.pause()

        assert "main.customer.customerid" in editor.text
```

`CatalogItem`, `DatabaseTree`, `wait_for_editor`, `wait_for_catalog_tree` и фикстура `app_multi_duck` уже доступны в этом файле — смотри его импорты и соседний тест на строке 184. Узлы добавляются свои, чтобы тест не зависел от того, какие таблицы лежат в duckdb-фикстуре.

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest tests/functional_tests/test_data_catalog.py::test_inserting_a_column_uses_its_alias -v`
Expected: FAIL — в буфере оказывается `"driver_id"`, а не `d.driver_id`

- [ ] **Step 3: Завести хранилище зарезервированных слов**

В `src/harlequin/app.py` добавить импорт (`CatalogItem` там уже импортирован на строке 50, повторно его добавлять не нужно):

```python
from harlequin.references import DEFAULT_RESERVED, path_for, read_scope
```

В `class CompletersReady(Message)` (строка 230) добавить параметр `reserved_words: frozenset[str]` — рядом с `word_completer` и `member_completer`, тем же способом, каким объявлены они.

В `__init__` приложения, рядом с `self.connection: HarlequinConnection | None = None` (строка 385):

```python
self.reserved_words: frozenset[str] = DEFAULT_RESERVED
```

- [ ] **Step 4: Наполнить его словами адаптера**

В `_build_completers` (строка 1747), после получения `extra_completions` и перед вызовом `completer_factory`:

```python
        # an adapter reserves more words than core knows about, and an
        # unquoted reserved word is a broken query rather than a long one
        adapter_reserved = frozenset(
            completion.label
            for completion in extra_completions
            if completion.type_label == "kw" and completion.priority == 100
        )
```

и передать его в сообщение:

```python
        self.post_message(
            CompletersReady(
                word_completer=word_completer,
                member_completer=member_completer,
                reserved_words=DEFAULT_RESERVED | adapter_reserved,
            )
        )
```

В обработчике `update_editor_completers` (строка 1066) первой строкой тела:

```python
        self.reserved_words = message.reserved_words
```

- [ ] **Step 5: Переписать обработчик вставки**

Заменить тело `insert_node_into_editor` (строки 581-590) на:

```python
    @on(HarlequinTree.NodeSubmitted)
    def insert_node_into_editor(self, message: HarlequinTree.NodeSubmitted) -> None:
        message.stop()
        if self.editor is None:
            # recycle message while editor loads
            callback = partial(self.post_message, message)
            self.set_timer(delay=0.1, callback=callback)
            return
        self.editor.insert_text_at_selection(text=self._insert_text_for(message))
        self.editor.focus()

    def _insert_text_for(self, message: HarlequinTree.NodeSubmitted) -> str:
        """What a submitted node puts in the editor.

        Only a catalog item gets a path: a file or an S3 key has no owner and no
        alias, and its own spelling is already what the query needs.
        """
        node = message.node
        if not isinstance(node.data, CatalogItem):
            return message.insert_name
        owner = node.parent.data if node.parent is not None else None
        assert self.editor is not None
        return path_for(
            item=node.data,
            owner=owner if isinstance(owner, CatalogItem) else None,
            scope=read_scope(self.editor.text),
            reserved=self.reserved_words,
        )
```

- [ ] **Step 6: Запустить новый тест**

Run: `pytest tests/functional_tests/test_data_catalog.py::test_inserting_a_column_uses_its_alias -v`
Expected: PASS

- [ ] **Step 6a: Обновить существующий тест под снятые кавычки**

В `test_double_click_inserts_node_into_editor` заменить

```python
        assert editor.text == '"small"'
```

на

```python
        assert editor.text == "small"
```

Это ровно то изменение поведения, ради которого всё делалось: имя базы `small` безопасно и в кавычках не нуждается. Если в буфере оказалось что-то другое — это регрессия, и подгонять ассерт нельзя.

- [ ] **Step 7: Убедиться, что не сломались файловое дерево и S3**

Run: `pytest tests/functional_tests/test_data_catalog.py -v`
Expected: PASS целиком. `test_file_tree` и `test_s3_tree` должны пройти **без единой правки** — их узлы не `CatalogItem`, и путь для них не строится.

- [ ] **Step 8: Прогнать весь набор**

Run: `pytest tests/unit_tests tests/functional_tests -q`
Expected: PASS. Снапшотные тесты каталога могли поменяться только если поменялся рендер — он не менялся; если какой-то упал, это регрессия, а не устаревший снапшот, и обновлять снапшот нельзя.

- [ ] **Step 9: Проверить руками на живой базе**

```bash
cd ~/src/harlequin && uv run harlequin -P retail
```

Набрать в редакторе `select \nfrom sales.customer c`, поставить курсор в первую строку, найти в каталоге `sales.customer.customerid`, нажать enter. Ожидается `c.customerid`. Затем убрать алиас из буфера и повторить — ожидается `sales.customer.customerid`.

- [ ] **Step 10: Коммит**

```bash
git add src/harlequin/app.py tests/functional_tests/test_data_catalog.py
git commit -m "feat: insert a usable path from the Data Catalog"
```

---

## Что этот план намеренно не делает

- Не трогает панель связей и всплывашку алиасов — они появятся в своих планах и позовут те же `read_scope()` и `path_for()`.
- Не добавляет настройку «всегда полный путь». Если правило начнёт мешать, это отдельный бинд, а не флаг в конфиге.
- Не чинит вставку из дерева файлов и S3 — там путь уже правильный.
