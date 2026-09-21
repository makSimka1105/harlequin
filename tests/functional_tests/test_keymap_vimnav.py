from __future__ import annotations

from typing import Awaitable, Callable

import pytest

from harlequin.adapter import HarlequinAdapter
from harlequin.app import Harlequin
from harlequin.plugins import load_keymap_plugins
from tests.functional_tests.helpers import wait_for_editor
from tests.waiting import wait_for


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


def test_vimnav_binds_pane_switching() -> None:
    from harlequin_vimnav import VIMNAV_APP_BINDINGS

    bound = {binding.keys: binding.action for binding in VIMNAV_APP_BINDINGS}

    assert bound["alt+h"] == "focus_data_catalog"
    assert bound["alt+j"] == "focus_results_viewer"
    assert bound["alt+k"] == "focus_query_editor"


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
