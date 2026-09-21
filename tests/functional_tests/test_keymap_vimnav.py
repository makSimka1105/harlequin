from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

import pytest

from harlequin.adapter import HarlequinAdapter
from harlequin.app import Harlequin
from harlequin.catalog import CatalogItem
from harlequin.plugins import load_keymap_plugins
from tests.functional_tests.helpers import (
    expand_catalog_node,
    wait_for_catalog_tree,
    wait_for_editor,
)
from tests.waiting import wait_for

if TYPE_CHECKING:
    from textual.pilot import Pilot


async def _settle_initial_editor_focus(pilot: Pilot, app: Harlequin) -> None:
    """Wait out the startup race before a test redirects focus itself.

    Mounting the first buffer posts `EditorCollection.EditorSwitched`, whose
    handler calls `self.editor.focus()`; that lands on the event loop at an
    unpredictable point relative to a test's own `.focus()` call, so a test
    that moves focus right after mounting can have it stolen back a beat
    later. Waiting for the editor to hold focus first drains that race.
    """
    await wait_for(
        pilot,
        lambda: app.editor is not None and app.editor.has_focus_within,
        description="the Query Editor to take its initial focus on startup",
    )


def test_vimnav_is_installed_as_a_keymap_plugin() -> None:
    keymaps = load_keymap_plugins(user_defined_keymaps=[])

    assert "vimnav" in keymaps


def test_vimnav_binds_tree_navigation() -> None:
    from harlequin_vimnav import VIMNAV_DATA_CATALOG_BINDINGS

    bound = {binding.keys: binding.action for binding in VIMNAV_DATA_CATALOG_BINDINGS}

    assert bound["j"] == "data_catalog.cursor_down"
    assert bound["k"] == "data_catalog.cursor_up"
    assert bound["J"] == "data_catalog.cursor_next_container"
    assert bound["K"] == "data_catalog.cursor_previous_container"
    assert bound["h"] == "data_catalog.collapse_node"
    assert bound["l"] == "data_catalog.expand_node"


def test_vimnav_binds_app_actions() -> None:
    """ctrl, not alt: with the kitty keyboard protocol on, alacritty reports
    alt+<letter> as its own key event that textual never recombines, so
    alt+ bindings silently never fire. Pane switching is mnemonic (e/r/d).
    """
    from harlequin_vimnav import VIMNAV_APP_BINDINGS

    app_bound = {b.keys: b.action for b in VIMNAV_APP_BINDINGS}
    # focus_query_editor and focus_results_viewer are bound per pane, not here:
    # vscode already owns ctrl+e and ctrl+r app-wide, and an app-level binding
    # added later does not replace an earlier one. The press tests below cover
    # them.
    assert app_bound["ctrl+d"] == "focus_data_catalog"
    assert app_bound["ctrl+shift+e,f4"] == "show_data_exporter"
    assert app_bound["ctrl+shift+r,f3"] == "refresh_catalog"
    assert app_bound["f7"] == "cancel_query"


def test_vimnav_binds_tab_switching() -> None:
    """j/k on the focused widget shadow vscode's bare j/k tab bindings, so
    those tab actions become unreachable by any key unless vimnav supplies
    its own binding for them on a key it does not already use for cursor
    movement.

    This only checks the keymap entries exist under the right names; it
    cannot catch a binding on a key Textual never produces (see
    `test_vimnav_bracket_bindings_actually_switch_results_tabs` below, which
    is what caught that).
    """
    from harlequin_vimnav import (
        VIMNAV_DATA_CATALOG_BINDINGS,
        VIMNAV_RESULTS_VIEWER_BINDINGS,
    )

    catalog_bound = {b.action: b.keys for b in VIMNAV_DATA_CATALOG_BINDINGS}
    results_bound = {b.action: b.keys for b in VIMNAV_RESULTS_VIEWER_BINDINGS}

    # Textual names "[" and "]" left_square_bracket/right_square_bracket
    # (textual.keys._character_to_key); a binding on the literal character
    # never matches a keypress.
    assert catalog_bound["data_catalog.previous_tab"] == "left_square_bracket"
    assert catalog_bound["data_catalog.next_tab"] == "right_square_bracket"
    assert results_bound["results_viewer.previous_tab"] == "left_square_bracket"
    assert results_bound["results_viewer.next_tab"] == "right_square_bracket"


def test_vimnav_actions_all_exist() -> None:
    from harlequin.actions import HARLEQUIN_ACTIONS
    from harlequin_vimnav import VIMNAV

    unknown = [
        binding.action
        for binding in VIMNAV.bindings
        if binding.action not in HARLEQUIN_ACTIONS
    ]

    assert unknown == []


@pytest.fixture
def app_with_vimnav(duckdb_adapter: type[HarlequinAdapter]) -> Harlequin:
    return Harlequin(
        duckdb_adapter([":memory:"], no_init=True),
        connection_hash="foo",
        keymap_names=["vscode", "vimnav"],
    )


@pytest.mark.asyncio
async def test_vimnav_bracket_bindings_actually_switch_results_tabs(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    """Regression: a binding on the literal "[" or "]" never fires, because
    Textual names those keys left_square_bracket/right_square_bracket. The
    keymap-listing assertions above would still pass with the bug present, so
    this presses the actual keys and checks the tab actually changed.
    """
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        editor = await wait_for_editor(pilot, app)

        editor.text = "select 1 as a; select 2 as b;"
        editor.focus()
        await pilot.press("ctrl+a")
        await pilot.press("ctrl+j")
        await wait_for_workers(app)
        await wait_for(
            pilot,
            lambda: app.results_viewer.tab_count > 1,
            description="the Results Viewer to show a tab per statement",
        )

        assert app.results_viewer.active == "result-1"

        app.results_viewer.focus()
        await pilot.press("]")
        await wait_for(
            pilot,
            lambda: app.results_viewer.active == "result-2",
            description="] to switch to the next results tab",
        )

        await pilot.press("[")
        await wait_for(
            pilot,
            lambda: app.results_viewer.active == "result-1",
            description="[ to switch back to the previous results tab",
        )


#######################################################
# Mnemonic pane switching
#######################################################


@pytest.mark.asyncio
async def test_vimnav_ctrl_r_from_editor_focuses_results_viewer(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)

        await pilot.press("ctrl+r")
        await wait_for(
            pilot,
            lambda: app.results_viewer.has_focus_within,
            description="ctrl+r from the Query Editor to focus the Results Viewer",
        )


@pytest.mark.asyncio
async def test_vimnav_ctrl_e_from_catalog_focuses_query_editor(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)

        app.data_catalog.focus()
        await pilot.pause()
        await pilot.press("ctrl+e")
        await wait_for(
            pilot,
            lambda: app.editor is not None and app.editor.has_focus_within,
            description="ctrl+e from the Data Catalog to focus the Query Editor",
        )


@pytest.mark.asyncio
async def test_vimnav_ctrl_d_from_results_viewer_focuses_data_catalog(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)

        app.results_viewer.focus()
        await pilot.pause()
        await pilot.press("ctrl+d")
        await wait_for(
            pilot,
            lambda: app.data_catalog.has_focus_within,
            description="ctrl+d from the Results Viewer to focus the Data Catalog",
        )


#######################################################
# h/l on catalog tree nodes
#######################################################


@pytest.mark.asyncio
async def test_vimnav_l_expands_a_collapsed_node(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)
        tree = await wait_for_catalog_tree(pilot, app)

        db_node = tree.root.children[0]
        assert db_node.is_expanded is False

        tree.focus()
        await pilot.pause()
        tree.move_cursor_to_line(db_node.line)
        await pilot.press("l")
        await wait_for(
            pilot,
            lambda: db_node.is_expanded,
            description="l to expand the collapsed database node",
        )


@pytest.mark.asyncio
async def test_vimnav_l_on_an_expanded_node_steps_into_its_first_child(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)
        tree = await wait_for_catalog_tree(pilot, app)

        db_node = tree.root.children[0]
        await expand_catalog_node(pilot, db_node)
        assert db_node.children

        tree.focus()
        await pilot.pause()
        tree.move_cursor_to_line(db_node.line)
        first_child_line = db_node.children[0].line
        await pilot.press("l")
        await wait_for(
            pilot,
            lambda: tree.cursor_line == first_child_line,
            description="l on an already-expanded node to step into its first child",
        )


@pytest.mark.asyncio
async def test_vimnav_l_on_a_leaf_node_does_nothing(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)
        tree = await wait_for_catalog_tree(pilot, app)

        leaf = tree.root.add_leaf(
            "probe",
            data=CatalogItem(
                qualified_identifier='"probe"',
                query_name='"probe"',
                label="probe",
                type_label="##",
            ),
        )
        tree.focus()
        await pilot.pause()
        tree.move_cursor_to_line(leaf.line)
        cursor_before = tree.cursor_line
        assert cursor_before == leaf.line

        await pilot.press("l")
        await pilot.pause()

        assert tree.cursor_line == cursor_before
        assert leaf.is_expanded is False


@pytest.mark.asyncio
async def test_vimnav_h_collapses_an_expanded_node(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)
        tree = await wait_for_catalog_tree(pilot, app)

        db_node = tree.root.children[0]
        await expand_catalog_node(pilot, db_node)
        assert db_node.is_expanded is True

        tree.focus()
        await pilot.pause()
        tree.move_cursor_to_line(db_node.line)
        await pilot.press("h")
        await wait_for(
            pilot,
            lambda: not db_node.is_expanded,
            description="h to collapse the expanded database node",
        )


@pytest.mark.asyncio
async def test_vimnav_h_on_a_collapsed_node_moves_cursor_to_its_parent(
    app_with_vimnav: Harlequin,
    wait_for_workers: Callable[[Harlequin], Awaitable[None]],
) -> None:
    app = app_with_vimnav
    async with app.run_test() as pilot:
        await wait_for_workers(app)
        await wait_for_editor(pilot, app)
        await _settle_initial_editor_focus(pilot, app)
        tree = await wait_for_catalog_tree(pilot, app)

        db_node = tree.root.children[0]
        await expand_catalog_node(pilot, db_node)
        schema_node = db_node.children[0]
        assert schema_node.is_expanded is False

        tree.focus()
        await pilot.pause()
        tree.move_cursor_to_line(schema_node.line)
        await pilot.press("h")
        await wait_for(
            pilot,
            lambda: tree.cursor_line == db_node.line,
            description="h on a collapsed node to move the cursor up to its parent",
        )
