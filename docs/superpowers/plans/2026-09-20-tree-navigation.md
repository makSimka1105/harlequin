# Навигация по дереву и раскладка vimnav — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** двигаться по каталогу вимовскими клавишами, включая прыжок `shift+j`/`shift+k` на следующий и предыдущий разворачиваемый узел — с колонки на таблицу, с последней таблицы схемы на следующую схему.

**Architecture:** два новых действия на `HarlequinTree`, реализованных сканом строк через публичное API textual, плюс отдельный пакет раскладки `harlequin_vimnav` по образцу существующего `harlequin_vscode`, подключаемый через entry point `harlequin.keymap`.

**Tech Stack:** Python 3.10+, textual 8.2.8, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-20-harlequin-fork-design.md`, раздел «3. Навигация по дереву».

## Global Constraints

- Ветка `maksibon-fork`, база — upstream `v2.15.0`. Раздел 1 спеки уже смерджен (коммиты `e57ccd5..36ca496`).
- Все команды — через `uv run` (`uv run pytest`, `uv run ruff check`, `uv run mypy`), из `/home/maksibon/src/harlequin`. Окружение синхронизировано, `uv sync` запускать не нужно.
- Известные падения, существующие до этой работы, — **15 идентификаторов**, чинить их не надо и регрессией они не являются: 11 падений и 2 ошибки в `tests/unit_tests/test_hsql.py`, `test_config_schema.py`, `test_config_wizard.py`, `test_import_hygiene.py`, плюс `tests/functional_tests/test_crash.py::test_a_crash_while_replaying_recovered_buffers_cannot_repeat` для sqlite и duckdb.
- Только публичное API textual. В `Tree._tree_lines` не лезть: приватное поле сделает каждый апгрейд textual лотереей.
- Стиль: `from __future__ import annotations` первой строкой, полные аннотации типов, докстроки объясняют «почему».

---

### Task 1: Прыжки по разворачиваемым узлам

**Files:**
- Modify: `src/harlequin/components/data_catalog/tree.py` (методы на `HarlequinTree`)
- Modify: `src/harlequin/actions.py:229-231` (регистрация двух действий)
- Test: `tests/functional_tests/test_data_catalog.py`

**Interfaces:**
- Consumes: `textual.widgets.Tree` — публичные `cursor_line`, `last_line`, `get_node_at_line(line)`, `move_cursor_to_line(line)`; `TreeNode.allow_expand`.
- Produces: действия `data_catalog.cursor_next_container` и `data_catalog.cursor_previous_container`, реализованные как `HarlequinTree.action_cursor_next_container()` и `action_cursor_previous_container()`.

**Почему предикат — `allow_expand`.** Harlequin выставляет его на `database_tree.py:447` как `bool(item.children) or not item.loaded`: у колонки False, у таблицы и схемы True, у узла-заглушки `loading…` False. Поэтому одно правило «следующий узел, который можно развернуть» само даёт нужное поведение на всех уровнях, без отдельных веток на таблицу и схему.

**Известное ограничение, чинить не надо:** таблица без единой колонки после загрузки получает `allow_expand = False` (`database_tree.py:561`) и будет прыжком пропускаться. Случай вырожденный.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/functional_tests/test_data_catalog.py`:

```python
@pytest.mark.asyncio
async def test_container_jumps_skip_columns(
    app_multi_duck: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_multi_duck
    async with app.run_test(size=(120, 36)) as pilot:
        await wait_for_workers(app)
        await wait_for_catalog_tree(pilot, app)

        # nodes of our own, so the test does not depend on the fixture's schema
        tree = app.data_catalog.database_tree
        first = tree.root.add("first", data=None)
        first.add_leaf("col_a", data=None)
        first.add_leaf("col_b", data=None)
        second = tree.root.add("second", data=None)
        second.add_leaf("col_c", data=None)
        first.expand()
        second.expand()
        await pilot.pause()

        tree.move_cursor_to_line(first.line)
        tree.action_cursor_next_container()
        assert tree.cursor_node is not None
        assert tree.cursor_node.label.plain == "second"

        # from a column, the next container is the following table, not the
        # next column
        tree.move_cursor_to_line(first.children[0].line)
        tree.action_cursor_next_container()
        assert tree.cursor_node is not None
        assert tree.cursor_node.label.plain == "second"

        tree.action_cursor_previous_container()
        assert tree.cursor_node is not None
        assert tree.cursor_node.label.plain == "first"


@pytest.mark.asyncio
async def test_container_jumps_stay_in_bounds(
    app_multi_duck: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_multi_duck
    async with app.run_test(size=(120, 36)) as pilot:
        await wait_for_workers(app)
        await wait_for_catalog_tree(pilot, app)

        tree = app.data_catalog.database_tree
        only = tree.root.add("only", data=None)
        only.add_leaf("col", data=None)
        only.expand()
        await pilot.pause()

        # no container after the last one: the cursor must not move or wrap
        tree.move_cursor_to_line(only.children[0].line)
        line_before = tree.cursor_line
        tree.action_cursor_next_container()
        assert tree.cursor_line == line_before
```

`wait_for_catalog_tree`, `app_multi_duck` и `Callable`/`Awaitable` уже доступны в этом файле — смотри его импорты.

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/functional_tests/test_data_catalog.py -k container -v`
Expected: FAIL с `AttributeError: 'DatabaseTree' object has no attribute 'action_cursor_next_container'`

- [ ] **Step 3: Реализовать методы**

В `src/harlequin/components/data_catalog/tree.py` дописать в класс `HarlequinTree`, рядом с существующими `action_*`:

```python
    def action_cursor_next_container(self) -> None:
        """Move to the next node that can be expanded, skipping leaves.

        A column is a leaf and a relation is not, so one rule covers both of
        the jumps this is for: from a column to the relation after it, and
        from a schema's last relation to the next schema.
        """
        self._move_to_container(step=1)

    def action_cursor_previous_container(self) -> None:
        self._move_to_container(step=-1)

    def _move_to_container(self, step: int) -> None:
        """Scan for the nearest expandable node in one direction.

        Scanning lines rather than walking the node graph is what keeps the
        jump honest about what is on screen: a collapsed relation's columns
        are nodes, but they occupy no line, and skipping them is the point.
        """
        line = self.cursor_line + step
        while 0 <= line <= self.last_line:
            node = self.get_node_at_line(line)
            if node is not None and node.allow_expand:
                self.move_cursor_to_line(line)
                return
            line += step
```

- [ ] **Step 4: Зарегистрировать действия**

В `src/harlequin/actions.py`, сразу после строки `"data_catalog.cursor_down"` (строка 231):

```python
    "data_catalog.cursor_next_container": Action(
        target=HarlequinTree, action="cursor_next_container"
    ),
    "data_catalog.cursor_previous_container": Action(
        target=HarlequinTree, action="cursor_previous_container"
    ),
```

- [ ] **Step 5: Запустить тесты**

Run: `uv run pytest tests/functional_tests/test_data_catalog.py -k container -v`
Expected: PASS, два теста

- [ ] **Step 6: Убедиться, что каталог целиком не сломался**

Run: `uv run pytest tests/functional_tests/test_data_catalog.py -q`
Expected: PASS (пропуски из-за отсутствия boto3 допустимы)

- [ ] **Step 7: Линтер и типы**

Run: `uv run ruff check src/harlequin tests && uv run mypy src/harlequin`
Expected: чисто

- [ ] **Step 8: Коммит**

```bash
git add src/harlequin/components/data_catalog/tree.py src/harlequin/actions.py tests/functional_tests/test_data_catalog.py
git commit -m "feat: jump between expandable nodes in the Data Catalog"
```

---

### Task 2: Пакет раскладки harlequin_vimnav

**Files:**
- Create: `src/harlequin_vimnav/__init__.py`
- Modify: `pyproject.toml:157-159` (секция `[project.entry-points."harlequin.keymap"]`)
- Test: `tests/functional_tests/test_keymap_vimnav.py`

**Interfaces:**
- Consumes: `harlequin.keymap.HarlequinKeyBinding`, `harlequin.keymap.HarlequinKeyMap`; действия из Task 1.
- Produces: `VIMNAV: HarlequinKeyMap` с именем `"vimnav"`, зарегистрированный как entry point `vimnav`.

**Почему пакетом, а не портянкой в конфиге.** Сейчас у пользователя двенадцать биндов расписаны прямо в `~/.config/harlequin/config.toml`. Пакет делает их версионируемыми вместе с кодом и покрытыми тестами, а конфиг схлопывается до одной строки `keymap_name = ["vscode", "vimnav"]`.

**Переключение панелей остаётся на `alt+hjkl`.** Аккорд `ctrl+w h` невозможен: textual последовательностей не поддерживает, запись `"ctrl+b,f9"` в существующей раскладке — это список альтернатив. `ctrl+hjkl` тоже отпадает: `ctrl+j` объявлен псевдонимом `newline` (`keys.py:254`) и уже занят запуском запроса в vscode-раскладке.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/functional_tests/test_keymap_vimnav.py`:

```python
from __future__ import annotations

from harlequin.plugins import load_keymap_plugins


def test_vimnav_is_installed_as_a_keymap_plugin() -> None:
    keymaps = load_keymap_plugins(user_defined_keymaps=[])

    assert "vimnav" in keymaps


def test_vimnav_binds_tree_navigation() -> None:
    from harlequin_vimnav import VIMNAV

    bound = {binding.keys: binding.action for binding in VIMNAV.bindings}

    assert bound["j"] == "data_catalog.cursor_down"
    assert bound["k"] == "data_catalog.cursor_up"
    assert bound["J"] == "data_catalog.cursor_next_container"
    assert bound["K"] == "data_catalog.cursor_previous_container"


def test_vimnav_binds_pane_switching() -> None:
    from harlequin_vimnav import VIMNAV

    bound = {binding.keys: binding.action for binding in VIMNAV.bindings}

    assert bound["alt+h"] == "focus_data_catalog"
    assert bound["alt+j"] == "focus_results_viewer"
    assert bound["alt+k"] == "focus_query_editor"


def test_vimnav_actions_all_exist() -> None:
    from harlequin.actions import HARLEQUIN_ACTIONS
    from harlequin_vimnav import VIMNAV

    unknown = [
        binding.action
        for binding in VIMNAV.bindings
        if binding.action not in HARLEQUIN_ACTIONS
    ]

    assert unknown == []
```

Сигнатура сверена по `src/harlequin/plugins.py:82`: `load_keymap_plugins(user_defined_keymaps)` — аргумент обязательный, поэтому передаётся пустой список.

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/functional_tests/test_keymap_vimnav.py -v`
Expected: FAIL — `vimnav` не найден среди плагинов, `harlequin_vimnav` не импортируется

- [ ] **Step 3: Написать пакет**

Создать `src/harlequin_vimnav/__init__.py`:

```python
"""Vim-style navigation, layered on top of another keymap.

Only navigation: this keymap binds no editing action, because the Query
Editor takes text and a bare letter there is typing, not a command. It is
meant to be loaded after a full keymap, e.g. keymap_name = ["vscode", "vimnav"].
"""

from __future__ import annotations

from harlequin.keymap import HarlequinKeyBinding, HarlequinKeyMap

VIMNAV_APP_BINDINGS = [
    # alt, not ctrl: ctrl+j is an alias of newline and ctrl+h of backspace,
    # and textual has no chords, so ctrl+w h is not available either
    HarlequinKeyBinding("alt+h", "focus_data_catalog"),
    HarlequinKeyBinding("alt+j", "focus_results_viewer"),
    HarlequinKeyBinding("alt+k", "focus_query_editor"),
    HarlequinKeyBinding("alt+p", "show_query_history"),
    HarlequinKeyBinding("alt+c", "cancel_query"),
]

VIMNAV_DATA_CATALOG_BINDINGS = [
    HarlequinKeyBinding("j", "data_catalog.cursor_down"),
    HarlequinKeyBinding("k", "data_catalog.cursor_up"),
    HarlequinKeyBinding("J", "data_catalog.cursor_next_container"),
    HarlequinKeyBinding("K", "data_catalog.cursor_previous_container"),
    HarlequinKeyBinding("l", "data_catalog.focus_query_editor"),
    HarlequinKeyBinding("h", "data_catalog.toggle_node"),
]

VIMNAV_RESULTS_VIEWER_BINDINGS = [
    HarlequinKeyBinding("j", "results_viewer.cursor_down"),
    HarlequinKeyBinding("k", "results_viewer.cursor_up"),
    HarlequinKeyBinding("h", "results_viewer.cursor_left"),
    HarlequinKeyBinding("l", "results_viewer.cursor_right"),
]

VIMNAV = HarlequinKeyMap(
    name="vimnav",
    bindings=[
        *VIMNAV_APP_BINDINGS,
        *VIMNAV_DATA_CATALOG_BINDINGS,
        *VIMNAV_RESULTS_VIEWER_BINDINGS,
    ],
)
```

- [ ] **Step 4: Зарегистрировать entry point**

В `pyproject.toml`, в секцию `[project.entry-points."harlequin.keymap"]` рядом со строкой `vscode = "harlequin_vscode:VSCODE"`:

```toml
vimnav = "harlequin_vimnav:VIMNAV"
```

Затем переустановить проект в окружение, чтобы entry point зарегистрировался:

Run: `uv sync --all-extras --all-groups`

**Сразу после этого шага harlequin перестанет запускаться**, пока не выполнен шаг 10. Причина: `~/.config/harlequin/config.toml` определяет keymap с именем `vimnav` инлайном, а `plugins.py:82-92` считает совпадение имени плагина и пользовательской раскладки конфликтом и поднимает `HarlequinConfigError`. Тесты это не затрагивает — они не читают пользовательский конфиг, — но любой ручной запуск до шага 10 упадёт с ошибкой конфига, и это ожидаемо.

- [ ] **Step 5: Запустить тесты раскладки**

Run: `uv run pytest tests/functional_tests/test_keymap_vimnav.py -v`
Expected: PASS, четыре теста

- [ ] **Step 6: Проверить, что vscode-раскладка не пострадала**

Run: `uv run pytest tests/functional_tests/test_keymap_vscode.py tests/functional_tests/test_keymap_from_config.py -q`
Expected: PASS

- [ ] **Step 7: Прогнать весь набор**

Run: `uv run pytest tests/unit_tests tests/functional_tests -q`
Expected: те же 15 известных падений и ни одного нового. `test_hsql.py` проверяет полноту `--info` по установленным плагинам — если новое падение окажется там, это ожидаемо и надо сообщить, а не чинить молча.

- [ ] **Step 8: Линтер и типы**

Run: `uv run ruff check src tests && uv run mypy src/harlequin src/harlequin_vimnav`
Expected: чисто

- [ ] **Step 9: Коммит**

```bash
git add src/harlequin_vimnav/__init__.py pyproject.toml uv.lock tests/functional_tests/test_keymap_vimnav.py
git commit -m "feat: ship a vimnav keymap plugin"
```

- [ ] **Step 10: Упростить пользовательский конфиг**

Заменить содержимое `~/.config/harlequin/config.toml` на:

```toml
default_profile = "retail"

[profiles.retail]
adapter = "postgres"
conn_str = ["postgres://postgres:postgres@localhost:5432/retail_training"]
theme = "catppuccin-mocha"
keymap_name = ["vscode", "vimnav"]
```

Прежнюю версию сохранить как `~/.config/harlequin/config.toml.inline-keymaps`, не удалять. Это файл вне репозитория — в коммит он не идёт.

- [ ] **Step 11: Проверить руками**

```bash
cd ~/src/harlequin && uv run harlequin -P retail
```

`alt+h` уводит в каталог, `j`/`k` двигают курсор по одной строке, `J`/`K` прыгают между таблицами и схемами, `alt+k` возвращает в редактор. Проверить, что в редакторе `j` и `k` по-прежнему печатают буквы, а не двигают курсор.

---

## Риск, о котором надо доложить, а не чинить молча

Голые буквы (`j`, `k`, `h`, `l`, `J`, `K`) биндятся впервые: вся существующая раскладка `vscode` использует только модифицированные клавиши и функциональные. `bindings.py:12` намеренно оставляет немодифицированные печатные клавиши обычному разбору textual, потому что их не отличить от набора текста. В дереве и в таблице результатов текст не набирают, так что бинды должны срабатывать — но это предположение, а не проверенный факт.

Если на шаге 11 голые буквы не сработают, **не подбирай замену на своё усмотрение**: опиши в отчёте, какие клавиши сработали, а какие нет, и в каком виджете. Выбор запасной раскладки — решение владельца, а не исполнителя.

## Что этот план намеренно не делает

- Не трогает редактор: модальный режим — отдельный раздел спеки и отдельный план. Здесь `j` и `k` в редакторе обязаны печататься.
- Не вводит счётчики (`3j`) и аккорды: textual последовательностей клавиш не поддерживает.
- Не чинит пропуск таблицы без колонок при прыжке — вырожденный случай, зафиксирован в спеке как известное ограничение.
