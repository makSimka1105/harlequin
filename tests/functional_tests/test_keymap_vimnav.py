from __future__ import annotations

from harlequin.plugins import load_keymap_plugins


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


def test_vimnav_actions_all_exist() -> None:
    from harlequin.actions import HARLEQUIN_ACTIONS
    from harlequin_vimnav import VIMNAV

    unknown = [
        binding.action
        for binding in VIMNAV.bindings
        if binding.action not in HARLEQUIN_ACTIONS
    ]

    assert unknown == []
