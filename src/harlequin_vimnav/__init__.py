"""Vim-style navigation, layered on top of another keymap.

Only navigation: this keymap binds no editing action, because the Query
Editor takes text and a bare letter there is typing, not a command. It is
meant to be loaded after a full keymap, e.g. keymap_name = ["vscode", "vimnav"].
"""

from __future__ import annotations

from harlequin.keymap import HarlequinKeyBinding, HarlequinKeyMap

VIMNAV_APP_BINDINGS = [
    # ctrl, not alt: with the kitty keyboard protocol on, alacritty reports
    # alt+<letter> as its own key event that textual never recombines with
    # the following letter, so alt+ bindings silently never fire. Pane
    # switching is mnemonic (e/r/d, matching each pane's first letter)
    # rather than relative like ctrl+w h in vim -- textual has no chords, so
    # that model is unavailable anyway.
    # ctrl+e and ctrl+r are already bound app-wide by vscode
    # (show_data_exporter, refresh_catalog). A later keymap does not replace an
    # earlier binding on the same key -- bindings accumulate and the first match
    # wins -- so the pane-switching versions have to be bound per pane, where
    # the focused widget is consulted before the app.
    # "d" for "data catalog": ctrl+c is taken by copy in all three panes, so
    # it can't stand for "catalog" here.
    HarlequinKeyBinding("ctrl+d", "focus_data_catalog"),
    # The per-pane ctrl+e/ctrl+r bindings shadow vscode's
    # show_data_exporter/refresh_catalog in every pane that has focus, so those
    # rare actions get a second key here: ctrl+shift+<letter>, each with an
    # f-key alternative so it stays reachable on a terminal that cannot report
    # ctrl+shift+<letter> at all.
    HarlequinKeyBinding("ctrl+shift+e,f4", "show_data_exporter"),
    HarlequinKeyBinding("ctrl+shift+r,f3", "refresh_catalog"),
    # cancel_query has no binding at all in the vscode keymap -- it only
    # ever lived on our own alt+x -- so it just needs one key that works
    # under any keyboard protocol.
    HarlequinKeyBinding("f7", "cancel_query"),
]

VIMNAV_EDITOR_BINDINGS = [
    HarlequinKeyBinding("ctrl+r", "code_editor.focus_results_viewer"),
    HarlequinKeyBinding("ctrl+d", "code_editor.focus_data_catalog"),
]

VIMNAV_DATA_CATALOG_BINDINGS = [
    HarlequinKeyBinding("ctrl+e", "data_catalog.focus_query_editor"),
    HarlequinKeyBinding("ctrl+r", "data_catalog.focus_results_viewer"),
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
    HarlequinKeyBinding("ctrl+e", "results_viewer.focus_query_editor"),
    HarlequinKeyBinding("ctrl+d", "results_viewer.focus_data_catalog"),
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
        *VIMNAV_EDITOR_BINDINGS,
        *VIMNAV_DATA_CATALOG_BINDINGS,
        *VIMNAV_RESULTS_VIEWER_BINDINGS,
    ],
)
