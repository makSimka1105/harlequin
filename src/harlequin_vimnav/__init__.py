"""Vim-style navigation, layered on top of another keymap.

Only navigation: this keymap binds no editing action, because the Query
Editor takes text and a bare letter there is typing, not a command. It is
meant to be loaded after a full keymap, e.g. keymap_name = ["vscode", "vimnav"].
"""

from __future__ import annotations

from harlequin.keymap import HarlequinKeyBinding, HarlequinKeyMap

VIMNAV_APP_BINDINGS = [
    # alt, not ctrl: ctrl+j is an alias of newline and ctrl+h of backspace,
    # and textual has no chords, so ctrl+w h is not available either.
    # Pane switching is mnemonic (alt+r/e/c, matching each pane's first
    # letter) rather than relative like ctrl+w h in vim. The published pipx
    # release cannot express the fork's relative, per-pane focus actions
    # (they are code, not bindings it can configure), so it only ever has
    # the unscoped focus_* actions bound directly here. One mnemonic model
    # shared by both builds beats a better model that only the fork has;
    # these mirror the owner's ~/.config/harlequin/config.toml bindings.
    HarlequinKeyBinding("alt+p", "show_query_history"),
    # alt+c now means "focus the catalog", so cancel moved off it to alt+x.
    HarlequinKeyBinding("alt+x", "cancel_query"),
    HarlequinKeyBinding("alt+r", "focus_results_viewer"),
    HarlequinKeyBinding("alt+e", "focus_query_editor"),
    HarlequinKeyBinding("alt+c", "focus_data_catalog"),
]

VIMNAV_DATA_CATALOG_BINDINGS = [
    HarlequinKeyBinding("j", "data_catalog.cursor_down"),
    HarlequinKeyBinding("k", "data_catalog.cursor_up"),
    HarlequinKeyBinding("J", "data_catalog.cursor_next_container"),
    HarlequinKeyBinding("K", "data_catalog.cursor_previous_container"),
    HarlequinKeyBinding("h", "data_catalog.collapse_node"),
    HarlequinKeyBinding("l", "data_catalog.expand_node"),
    # vscode's j/k tab bindings are the only way to reach these actions, and
    # our own j/k win the binding walk on the focused catalog tree, so those
    # two would otherwise become unreachable by any key.
    # Textual names these keys left_square_bracket/right_square_bracket
    # (see textual.keys._character_to_key); binding the literal "[" or "]"
    # never matches a keypress, so the action silently never fires.
    HarlequinKeyBinding("left_square_bracket", "data_catalog.previous_tab"),
    HarlequinKeyBinding("right_square_bracket", "data_catalog.next_tab"),
]

VIMNAV_RESULTS_VIEWER_BINDINGS = [
    HarlequinKeyBinding("j", "results_viewer.cursor_down"),
    HarlequinKeyBinding("k", "results_viewer.cursor_up"),
    HarlequinKeyBinding("h", "results_viewer.cursor_left"),
    HarlequinKeyBinding("l", "results_viewer.cursor_right"),
    # same story as the data catalog: vscode's only bindings for these two
    # are bare j/k, which our own j/k shadow on the focused results table.
    # Textual names these keys left_square_bracket/right_square_bracket
    # (see textual.keys._character_to_key); binding the literal "[" or "]"
    # never matches a keypress, so the action silently never fires.
    HarlequinKeyBinding("left_square_bracket", "results_viewer.previous_tab"),
    HarlequinKeyBinding("right_square_bracket", "results_viewer.next_tab"),
]

VIMNAV = HarlequinKeyMap(
    name="vimnav",
    bindings=[
        *VIMNAV_APP_BINDINGS,
        *VIMNAV_DATA_CATALOG_BINDINGS,
        *VIMNAV_RESULTS_VIEWER_BINDINGS,
    ],
)
