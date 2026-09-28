"""Pick a table to join to the statement under the cursor, then name its aliases."""

from __future__ import annotations

from typing import Callable, Sequence, Union

from rich.style import Style
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from harlequin.relations.graph import Route
from harlequin.relations.joins import JoinRefusal
from harlequin.relations.spelling import table_name
from harlequin.relations_service import Edit, JoinCandidate

DIM = Style(dim=True)
BOLD = Style(bold=True)
NAME_WIDTH = 18
ALIAS_KEYS = "enter/tab ↓ · shift+tab ↑ · ctrl+enter ✓"

PlanJoin = Callable[[Route, Sequence[str]], Union[Edit, JoinRefusal]]


def route_label(route: Route, source: str | None = None) -> Text:
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
        f"{table_name(link.far_relation):<{NAME_WIDTH}}",
        (f" {link.cardinality}{mark} ", DIM),
        f"{source}.{columns}" if source else columns,
    )


class JoinPicker(ModalScreen[Union[Edit, JoinRefusal, None]]):
    BINDINGS = [
        Binding("escape", "back", show=False),
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
        Binding("tab", "move(1)", show=False),
        Binding("shift+tab", "move(-1)", show=False),
        Binding("ctrl+enter", "insert", show=False),
    ]

    def __init__(
        self,
        candidates: Sequence[JoinCandidate],
        empty_message: str,
        plan_join: PlanJoin,
    ) -> None:
        super().__init__()
        self._all = list(candidates)
        self._shown = list(candidates)
        self._empty_message = empty_message
        self._plan_join = plan_join
        self._renaming: JoinCandidate | None = None
        self._alias_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="join_picker"):
            yield Input(placeholder="фильтр", id="join_filter")
            yield OptionList(id="join_candidates")
            yield Static(id="join_preview")
            yield Vertical(id="join_aliases")

    def on_mount(self) -> None:
        self._show_routes()
        self._refill()
        self.call_after_refresh(self._pin_top)

    def on_resize(self, event: events.Resize) -> None:
        self.styles.align_vertical = "middle"
        self.query_one("#join_picker").styles.margin = 0
        self.call_after_refresh(self._pin_top)

    def _pin_top(self) -> None:
        """Grow and shrink from the bottom edge only, so the list does not jump."""
        box = self.query_one("#join_picker")
        box.styles.margin = (box.region.y, 0, 0, 0)
        self.styles.align_vertical = "top"

    @on(Input.Changed, "#join_filter")
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

    @on(Input.Submitted, "#join_filter")
    async def _submit_route(self) -> None:
        await self._rename(self._highlighted())

    @on(OptionList.OptionSelected)
    async def _select_route(self, event: OptionList.OptionSelected) -> None:
        await self._rename(self._shown[event.option_index])

    @on(Input.Submitted, "#join_aliases Input")
    def _submit_alias(self) -> None:
        if self._alias_index < len(self._alias_inputs()) - 1:
            self.action_move(1)
        else:
            self.action_insert()

    @on(Input.Changed, "#join_aliases Input")
    def _check_aliases(self) -> None:
        self._plan_with_aliases()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        alias_inputs = self._alias_inputs()
        if event.widget in alias_inputs:
            self._alias_index = alias_inputs.index(event.widget)
            for row in self.query(".alias_row"):
                row.set_class(row is event.widget.parent, "-current")
            self._show_progress()

    def action_move(self, delta: int) -> None:
        if self._renaming is not None:
            alias_inputs = self._alias_inputs()
            target = min(max(self._alias_index + delta, 0), len(alias_inputs) - 1)
            alias_inputs[target].focus()
            return
        options = self.query_one(OptionList)
        if delta > 0:
            options.action_cursor_down()
        else:
            options.action_cursor_up()

    def action_insert(self) -> None:
        if self._renaming is None:
            candidate = self._highlighted()
            if candidate is not None:
                self.dismiss(self._plan_join(candidate.route, ()))
            return
        plan = self._plan_with_aliases()
        if not isinstance(plan, JoinRefusal):
            self.dismiss(plan)

    def action_back(self) -> None:
        if self._renaming is None:
            self.dismiss(None)
        else:
            self._show_routes()

    async def _rename(self, candidate: JoinCandidate | None) -> None:
        if candidate is None:
            return
        if not candidate.aliases:
            self.dismiss(self._plan_join(candidate.route, ()))
            return
        self._renaming = candidate
        self._alias_index = 0
        alias_inputs = [
            Input(slot.alias, placeholder=slot.alias, restrict=r"[a-z0-9_]*")
            for slot in candidate.aliases
        ]
        aliases_box = self.query_one("#join_aliases")
        await aliases_box.remove_children()
        await aliases_box.mount_all(
            Horizontal(
                Label("▸", classes="alias_marker"),
                Label(table_name(slot.relation), classes="alias_table"),
                alias_input,
                classes="alias_row",
            )
            for slot, alias_input in zip(candidate.aliases, alias_inputs, strict=True)
        )
        self._set_stage(renaming=True)
        self._show_progress()
        self.query_one("#join_picker").border_subtitle = ALIAS_KEYS
        alias_inputs[0].focus()

    def _show_routes(self) -> None:
        self._renaming = None
        self._set_stage(renaming=False)
        box = self.query_one("#join_picker")
        box.border_title = "Join"
        box.border_subtitle = ""
        self.query_one("#join_filter", Input).focus()

    def _set_stage(self, renaming: bool) -> None:
        for route_part in ("#join_filter", "#join_candidates", "#join_preview"):
            self.query_one(route_part).display = not renaming
        self.query_one("#join_aliases").display = renaming

    def _show_progress(self) -> None:
        assert self._renaming is not None
        alias_count = len(self._renaming.aliases)
        done = self._alias_index + 1
        dots = "●" * done + "○" * (alias_count - done)
        self.query_one(
            "#join_picker"
        ).border_title = f"Join › алиасы {dots} {done}/{alias_count}"

    def _plan_with_aliases(self) -> Edit | JoinRefusal:
        assert self._renaming is not None
        alias_inputs = self._alias_inputs()
        plan = self._plan_join(
            self._renaming.route, [alias_input.value for alias_input in alias_inputs]
        )
        bad_slot = plan.slot if isinstance(plan, JoinRefusal) else None
        for index, alias_input in enumerate(alias_inputs):
            alias_input.set_class(index == bad_slot, "-invalid")
        self.query_one("#join_picker").border_subtitle = (
            plan.reason if isinstance(plan, JoinRefusal) else ALIAS_KEYS
        )
        return plan

    def _alias_inputs(self) -> list[Input]:
        return list(self.query("#join_aliases Input").results(Input))

    def _highlighted(self) -> JoinCandidate | None:
        index = self.query_one(OptionList).highlighted
        if index is not None and 0 <= index < len(self._shown):
            return self._shown[index]
        return None

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
