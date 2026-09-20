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
