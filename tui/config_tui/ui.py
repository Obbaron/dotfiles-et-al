"""The two-panel config editor (archinstall style).

Layout: the LEFT list is where control lives; the RIGHT panel previews the
highlighted node's children. Enter/l descends; h/escape ascends, restoring
the cursor. The config is a tree: sections -> profiles/modules -> items.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from config_tui import spec
from config_tui.keymap import keybinds_path, load_user_keymap, pair
from config_tui.settings import load_theme, save_theme
from config_tui.store import ConfigStore, StoreError
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Input,
    Label,
    OptionList,
    Select,
    SelectionList,
    Static,
    Switch,
    TextArea,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

ICONS: dict[str, str] = {
    "profiles": "\uf007",
    "packages": "\uf1b2",
    "directories": "\uf07b",
    "git": "\ue725",
    "files": "\uf15c",
    "fonts": "\uf031",
    "links": "\uf0c1",
    "services": "\uf013",
    "commands": "\uf120",
}

BARE_FIELD: dict[str, str] = {
    "packages": "name",
    "directories": "path",
    "fonts": "name",
}

FORM_FIELDS: dict[str, tuple[str, ...]] = {
    **dict(spec.ITEM_FIELD_ORDER),
    "fonts": ("name",),
}

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "packages": ("name",),
    "directories": ("path",),
    "git": ("url", "target"),
    "files": ("path",),
    "fonts": ("name",),
    "links": ("src", "dest"),
    "services": ("name",),
    "commands": ("run",),
}

TRISTATE = [("leave as-is", "unset"), ("true", "true"), ("false", "false")]


class FormError(Exception):
    """Raised when the current form inputs are not a valid item."""


@dataclass(frozen=True)
class Node:
    """A location in the config tree the navigator can point at."""

    kind: str  # "section" | "profile" | "module" | "item" | "ref"
    section: str  # "profiles" or a step name
    name: str = ""  # profile/module name
    index: int = -1  # item index within a module


def theme_palette(app: App) -> dict[str, str]:
    """Concrete colors for Rich renderables, resolved from the active theme
    (CSS gets theme variables directly; Rich styles need real colors)."""
    tv = app.theme_variables
    return {
        "title": tv.get("secondary", tv.get("primary", "#56b6c2")),
        "accent": tv.get("accent", "#e0af68"),
        "text": tv.get("foreground", "#c0c0c0"),
        "muted": "dim",
        "error": tv.get("error", "#e06c75"),
        "success": tv.get("success", "#98c379"),
    }


# ROW
def sidebar_row(icon: str, name: str, count: str, pal: dict[str, str]) -> Table:
    grid = Table.grid(padding=(0, 1), expand=True)
    grid.add_column(width=2, no_wrap=True)
    grid.add_column(no_wrap=True, overflow="ellipsis", justify="left", ratio=1)
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(
        Text(icon, style=pal["title"]), Text(name), Text(count, style=pal["accent"])
    )
    return grid


def preview_row(
    name: str, count: str, detail: str, widths: tuple[int, int], pal: dict[str, str]
) -> Table:
    grid = Table.grid(padding=(0, 2))

    grid.add_column(width=widths[0], no_wrap=True)
    grid.add_column(width=widths[1], no_wrap=True)
    grid.add_column(overflow="fold")
    grid.add_row(Text(name, style="bold"), count, Text(detail, style=pal["muted"]))

    return grid


def detail_lines(pairs: list[tuple[str, str]], pal: dict[str, str]) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style=pal["title"], no_wrap=True)
    grid.add_column(overflow="fold")

    for key, value in pairs:
        grid.add_row(key, value)

    return grid


def module_preview(
    store: ConfigStore,
    step: str,
    module: str,
    pal: dict[str, str],
    heading: bool = False,
) -> list[Option | None]:
    """Preview rows for one module: optional heading, requires, items."""
    rows: list[Option | None] = []

    if heading:
        rows.append(Option(Text(f"{step}.{module}", style=f"bold {pal['title']}")))

    requires = store.requires(step, module)
    if requires:
        rows.append(Option(detail_lines([("requires", ", ".join(requires))], pal)))

    for item in store.items(step, module):
        rows.append(Option(Text(f"  {spec.summarize_item(step, item)}")))

    if not store.items(step, module) and not requires:
        rows.append(Option(Text("  (empty module)", style=pal["muted"])))

    return rows


def ref_preview(
    store: ConfigStore, ref: str, pal: dict[str, str]
) -> list[Option | None]:
    """Preview rows for a ref: every module it resolves to, with contents."""
    targets = spec.ref_targets(store.plain(), ref)

    if not targets:
        return [Option(Text("  ✗ unresolved reference", style=f"bold {pal['error']}"))]

    rows: list[Option | None] = []
    for step, module in targets:
        rows.extend(module_preview(store, step, module, pal, heading=True))
        rows.append(None)

    return rows[:-1]


# WIDGETS
class HeaderBar(Static):
    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self._store = store

    def render(self) -> Text:
        pal = theme_palette(self.app)
        marker = (
            ("  [modified]", f"bold {pal['accent']}") if self._store.dirty else ("", "")
        )
        return Text.assemble(
            ("dotfiles-et-al config editor", "bold"),
            (" — ", pal["muted"]),
            (str(self._store.path), f"bold {pal['title']}"),
            marker,
            end="",
        )


class FooterBar(Static):
    """Key hints: a constant set plus context-dependent extras.

    Labels show the default keys; remaps via keybinds.toml change behavior
    but not (yet) these hints.
    """

    DEFAULT_CONSTANT = [
        ("esc", "Back"),
        ("enter", "Open"),
        ("^s", "Save"),
        ("^q", "Quit"),
    ]

    def __init__(self, id: str | None = None) -> None:  # noqa: A002 - Textual API
        super().__init__(id=id)
        self._constant: list[tuple[str, str]] = list(self.DEFAULT_CONSTANT)
        self._extras: list[tuple[str, str]] = []

    def set_hints(
        self,
        extras: list[tuple[str, str]],
        constant: list[tuple[str, str]] | None = None,
    ) -> None:
        self._constant = (
            list(constant) if constant is not None else list(self.DEFAULT_CONSTANT)
        )
        self._extras = extras
        self.refresh()

    def render(self) -> Table:
        pal = theme_palette(self.app)

        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1)
        grid.add_column(justify="right", no_wrap=True)

        left = Text()

        for key, label in [*self._constant, *self._extras]:
            left.append(key, f"bold {pal['accent']}")
            left.append(f" {label}   ")

        grid.add_row(
            left, Text.assemble(("^p", f"bold {pal['accent']}"), (" Commands", ""))
        )

        return grid


class NavList(OptionList):
    """Left column: where control lives. Navigation binds here (dual key
    sets from the keymap), sharing OptionList's action names so the keys
    panel shows one row per action. Inherited horizontal-scroll keys are
    shadowed (left is Back; ctrl+pgup/pgdn page vertically, hidden)."""

    BINDINGS: ClassVar = [
        *pair("browse.up", "cursor_up", "Up", show=False),
        *pair("browse.down", "cursor_down", "Down", show=False),
        *pair("browse.first", "first", "First", show=False),
        *pair("browse.last", "last", "Last", show=False),
        *pair("browse.page_down", "page_down", "Page Down", show=False),
        *pair("browse.page_up", "page_up", "Page Up", show=False),
        *pair("browse.open", "select", "Open", show=False),
        *pair("browse.back", "screen.ascend", "Back", show=False),
        Binding("ctrl+pageup", "page_up", "", show=False, system=True),
        Binding("ctrl+pagedown", "page_down", "", show=False, system=True),
    ]


class PickerList(SelectionList[str]):
    """Toggleable ref list for the picker screen (same navigation feel)."""

    BINDINGS: ClassVar = [
        *pair("picker.up", "cursor_up", "Up", show=False),
        *pair("picker.down", "cursor_down", "Down", show=False),
        *pair("picker.first", "first", "First", show=False),
        *pair("picker.last", "last", "Last", show=False),
        *pair("picker.toggle", "select", "Toggle", show=False),
        *pair("picker.cancel", "screen.cancel", "Cancel", show=False),
        Binding("ctrl+pageup", "page_up", "", show=False, system=True),
        Binding("ctrl+pagedown", "page_down", "", show=False, system=True),
    ]


class PreviewList(OptionList, can_focus=False):
    """Right panel: read-only preview of the highlighted node's children."""


class FormPanel(VerticalScroll):
    """Container for the in-panel item form. Its bindings are only active
    while focus is inside the form, so ctrl+q cancels the form here but
    still quits the app elsewhere. form.save is priority so ctrl+w beats
    Input's delete-word-left, per the keybind spec."""

    BINDINGS: ClassVar = [
        *pair("form.save", "screen.form_save", "Save item", priority=True, show=False),
        *pair("form.cancel", "screen.dismiss_overlay", "Cancel", show=False),
    ]


class StatusLine(Static):
    """Bottom-left, unboxed: the currently selected node."""

    def show(self, crumbs: list[str], selected: str) -> None:
        pal = theme_palette(self.app)
        text = Text()
        for crumb in crumbs:
            text.append(crumb, pal["muted"])
            text.append(" › ", pal["muted"])
        text.append(selected, "bold")
        self.update(text)


class CmdLine(Horizontal):
    """Vim-style bottom command line: prompts and confirms live here."""

    def compose(self) -> ComposeResult:
        yield Static("", id="cmd-label")
        yield Input(id="cmd-input")

    def hide(self) -> None:
        self.display = False
        self.query_one("#cmd-input", Input).display = False

    def ask(self, label: str, value: str = "") -> None:
        pal = theme_palette(self.app)
        self.display = True
        self.query_one("#cmd-label", Static).update(
            Text(f"{label} › ", style=f"bold {pal['accent']}")
        )
        field = self.query_one("#cmd-input", Input)
        field.display = True
        field.value = value
        field.focus()

    def say(self, message: Text) -> None:
        self.display = True
        self.query_one("#cmd-input", Input).display = False
        self.query_one("#cmd-label", Static).update(message)


# VALIDATION
class ValidationScreen(ModalScreen[None]):
    """Centered popup with the validation report; esc/enter/v closes."""

    BINDINGS: ClassVar = [
        Binding("escape,enter,v,ctrl+v", "dismiss_popup", "Close", show=False),
    ]

    def __init__(self, issues: list[spec.Issue]) -> None:
        super().__init__()
        self._issues = issues

    def compose(self) -> ComposeResult:
        with Vertical(id="val-box"):
            yield Static("", id="val-title")
            yield VerticalScroll(id="val-issues")
            yield Static("", id="val-hint")

    def on_mount(self) -> None:
        pal = theme_palette(self.app)
        ok = not self._issues
        title = (
            "validation — config is valid"
            if ok
            else f"validation — {len(self._issues)} issue(s)"
        )
        self.query_one("#val-title", Static).update(
            Text(title, style=f"bold {pal['success'] if ok else pal['error']}")
        )
        body = self.query_one("#val-issues", VerticalScroll)

        if ok:
            body.mount(Static(Text("✓ no issues found", style=pal["success"])))
        else:
            for issue in self._issues:
                body.mount(Static(detail_lines([(issue.location, issue.message)], pal)))

        self.query_one("#val-hint", Static).update(
            Text.assemble(("esc", f"bold {pal['accent']}"), (" close", pal["muted"]))
        )

    def action_dismiss_popup(self) -> None:
        self.dismiss(None)


# REF PICKER
class RefPickerScreen(Screen[list[str] | None]):
    """Toggleable ref list with a live preview of the highlighted ref.

    A ``*.name`` wildcard stands for every ``step.name`` module, so while a
    wildcard is selected its individual members are redundant: they are
    hidden from the list (and left unselected) to avoid the visual
    contradiction of a wildcard and its members toggling independently.
    Unselecting the wildcard brings the members back, unselected.

    The visible ``SelectionList`` is rebuilt whenever a wildcard's state
    changes; ``_selected`` is the stable source of truth across rebuilds.
    """

    BINDINGS: ClassVar = [
        *pair("picker.accept", "accept", "Accept", priority=True, show=False),
    ]

    def __init__(
        self, store: ConfigStore, title: str, choices: list[str], selected: list[str]
    ) -> None:
        super().__init__()
        self.store = store
        self._title = title
        self._choices = choices
        self._selected = set(selected)
        # ref -> set of "step.module" members it covers ("" for non-wildcards)
        self._members: dict[str, set[str]] = {
            ref: (
                {f"{s}.{m}" for s, m in spec.ref_targets(store.plain(), ref)}
                if ref.startswith("*.")
                else set()
            )
            for ref in choices
        }
        self._suppress = False  # guard against our own rebuild's toggle events

    def compose(self) -> ComposeResult:
        yield HeaderBar(self.store)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("", id="nav-title")
                yield PickerList(id="picker")
                yield StatusLine(id="status")
            with Vertical(id="main"):
                yield Static("", id="preview-title")
                yield PreviewList(id="preview")
        yield FooterBar(id="footer")

    def on_mount(self) -> None:
        self.query_one("#footer", FooterBar).set_hints(
            [],
            constant=[("esc", "Cancel"), ("enter", "Accept"), ("space", "Toggle")],
        )
        self._populate()
        self.query_one(PickerList).focus()
        self.on_theme_refresh()

    def _hidden_members(self) -> set[str]:
        """Members covered by a currently-selected wildcard (so, hidden)."""
        hidden: set[str] = set()
        for ref in self._selected:
            hidden |= self._members.get(ref, set())
        return hidden

    def _visible_choices(self) -> list[str]:
        hidden = self._hidden_members()
        return [ref for ref in self._choices if ref not in hidden]

    def _populate(self, keep_ref: str | None = None) -> None:
        """(Re)build the SelectionList from the model, filtering hidden members.

        keep_ref, when still visible, is re-highlighted so rebuilding the
        list doesn't jump the cursor.
        """
        picker = self.query_one(PickerList)
        visible = self._visible_choices()
        self._suppress = True
        picker.clear_options()
        picker.add_options(
            [Selection(ref, ref, ref in self._selected) for ref in visible]
        )
        self._suppress = False

        if visible:
            target = keep_ref if keep_ref in visible else None
            picker.highlighted = visible.index(target) if target else 0

    def on_theme_refresh(self) -> None:
        pal = theme_palette(self.app)
        self.query_one("#nav-title", Static).update(
            Text(self._title, style=f"bold {pal['title']}")
        )
        self._refresh_preview()

    def _current_ref(self) -> str | None:
        picker = self.query_one(PickerList)
        visible = self._visible_choices()
        if picker.highlighted is None or picker.highlighted >= len(visible):
            return None
        return visible[picker.highlighted]

    def _refresh_preview(self) -> None:
        pal = theme_palette(self.app)
        preview = self.query_one(PreviewList)
        preview.clear_options()
        ref = self._current_ref()
        if ref is None:
            self.query_one("#preview-title", Static).update(Text(""))
            return
        marker = "◉ selected" if ref in self._selected else "○ not selected"
        self.query_one("#preview-title", Static).update(
            Text.assemble(
                (f"{ref}", f"bold {pal['title']}"), (f"   {marker}", pal["muted"])
            )
        )
        preview.add_options(ref_preview(self.store, ref, pal))
        crumbs = self._title.split(" › ")[:-1]
        self.query_one(StatusLine).show(crumbs or ["refs"], ref)

    def on_selection_list_selection_highlighted(
        self, _event: SelectionList.SelectionHighlighted
    ) -> None:
        # Cursor moved: preview the ref we're about to toggle.
        self._refresh_preview()

    def on_selection_list_selected_changed(
        self, _event: SelectionList.SelectedChanged
    ) -> None:
        if self._suppress:
            return

        picker = self.query_one(PickerList)
        visible = self._visible_choices()
        now_selected = set(picker.selected)

        # Sync the model for every visible ref (captures the just-toggled one).
        for ref in visible:
            if ref in now_selected:
                self._selected.add(ref)
            else:
                self._selected.discard(ref)

        # Clean slate: members covered by a selected wildcard are dropped.
        hidden = self._hidden_members()
        needs_rebuild = set(visible) != set(self._visible_choices())

        if hidden & self._selected:
            self._selected -= hidden
            needs_rebuild = True

        if needs_rebuild:
            # Rebuild after this event settles: clearing/re-adding options
            # mid-dispatch tears down the widget the event came from.
            keep = self._current_ref()
            self.call_after_refresh(self._populate_and_preview, keep)
        else:
            self._refresh_preview()

    def _populate_and_preview(self, keep_ref: str | None) -> None:
        self._populate(keep_ref=keep_ref)
        self._refresh_preview()

    def action_accept(self) -> None:
        self.dismiss([ref for ref in self._choices if ref in self._selected])

    def action_cancel(self) -> None:
        self.dismiss(None)


# MAIN EDITOR SCREEN
class EditorScreen(Screen):
    """Single screen; `self.path` (a list of Nodes) is the tree location.

    Overlay modes (one at a time): "form" (item editor in the main panel),
    "prompt"/"confirm"/"quit" (the bottom command line). Escape dismisses
    the active overlay. Validation opens as a modal popup, not a mode.
    """

    BINDINGS: ClassVar = [
        *pair("actions.edit", "edit", "Edit", show=False),
        *pair("actions.new", "new", "New", show=False),
        *pair("actions.rename", "rename_or_requires", "Rename / Requires", show=False),
        *pair("actions.delete", "delete", "Delete", show=False),
        # Overlay plumbing (hidden from the keys panel)
        Binding("escape", "dismiss_overlay", "", show=False, system=True),
        Binding("y", "confirm_yes", "", show=False, system=True),
    ]

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self.path: list[Node] = []  # [] = root (sections)
        self._nav_nodes: list[Node] = []  # node per nav row
        self._history: list[int] = []  # cursor position per ascended level
        self._mode: str | None = None  # form|prompt|confirm|quit
        self._on_prompt: Any = None
        self._on_confirm: Any = None
        self._form_node: Node | None = None
        self._form_step: str = ""

    # COMPOSITION
    def compose(self) -> ComposeResult:
        yield HeaderBar(self.store)
        yield FooterBar(id="footer")
        yield CmdLine(id="cmdline")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static(id="nav-title")
                yield NavList(id="nav")
                yield StatusLine(id="status")
            with Vertical(id="main"):
                yield Static("", id="preview-title")
                yield PreviewList(id="preview")
                yield FormPanel(id="form")

    def on_mount(self) -> None:
        self.query_one("#cmdline", CmdLine).hide()
        self.query_one("#form").display = False
        self.query_one(NavList).focus()
        self.rebuild()

    def on_theme_refresh(self) -> None:
        nav = self.query_one(NavList)
        self.rebuild(highlight=nav.highlighted or 0)

    def _mutated(self, highlight: int | None = None) -> None:
        """Refresh everything after a store mutation."""
        nav = self.query_one(NavList)
        self.rebuild(highlight=nav.highlighted or 0 if highlight is None else highlight)
        self.query_one(HeaderBar).refresh()

    # TREE
    def _children(self, node: Node | None) -> list[Node]:
        if node is None:
            return [Node("section", "profiles")] + [
                Node("section", step) for step in spec.STEP_ORDER
            ]

        if node.kind == "section" and node.section == "profiles":
            return [Node("profile", "profiles", name) for name in self.store.profiles()]

        if node.kind == "section":
            return [
                Node("module", node.section, name)
                for name in self.store.module_names(node.section)
            ]

        if node.kind == "profile":
            refs = self.store.profiles().get(node.name, [])
            return [Node("ref", "profiles", ref) for ref in refs]

        if node.kind == "module":
            items = self.store.items(node.section, node.name)
            return [
                Node("item", node.section, node.name, index)
                for index in range(len(items))
            ]

        return []

    # LABELS/PREVIEWS
    def _nav_option(self, node: Node, pal: dict[str, str]) -> Option:
        if node.kind == "section":
            count = (
                len(self.store.profiles())
                if node.section == "profiles"
                else len(self.store.module_names(node.section))
            )
            return Option(
                sidebar_row(ICONS[node.section], node.section, str(count), pal)
            )

        if node.kind in ("profile", "module"):
            return Option(
                sidebar_row("", node.name, str(len(self._children(node))), pal)
            )

        if node.kind == "ref":
            return Option(sidebar_row("", node.name, "", pal))

        item = self.store.items(node.section, node.name)[node.index]
        return Option(sidebar_row("", spec.summarize_item(node.section, item), "", pal))

    def _preview_title(self, node: Node | None) -> str:
        if node is None:
            return ""

        if node.kind == "section" and node.section == "profiles":
            return f"profiles — {len(self.store.profiles())} profile(s)"

        if node.kind == "section":
            n = len(self.store.module_names(node.section))
            return f"{node.section} — {n} module(s)"

        if node.kind == "profile":
            refs = self.store.profiles().get(node.name, [])
            return f"profile {node.name} — {len(refs)} ref(s)"

        if node.kind == "module":
            n = len(self.store.items(node.section, node.name))
            return f"{node.section}.{node.name} — {n} item(s)"

        if node.kind == "ref":
            return f"ref {node.name}"

        return f"{node.section}.{node.name} · item {node.index + 1}"

    def _preview_options(
        self, node: Node | None, pal: dict[str, str]
    ) -> list[Option | None]:
        if node is None:
            return []

        if node.kind == "section" and node.section == "profiles":
            profiles = self.store.profiles()
            widths = (max((len(n) for n in profiles), default=0), len("99 ref(s)"))
            rows: list[Option | None] = []

            for name, refs in profiles.items():
                rows.append(
                    Option(
                        preview_row(
                            name, f"{len(refs)} ref(s)", ", ".join(refs), widths, pal
                        )
                    )
                )
                rows.append(None)

            return rows[:-1] if rows else []

        if node.kind == "section":
            modules = self.store.module_names(node.section)
            widths = (max((len(m) for m in modules), default=0), len("99 item(s)"))
            rows = []

            for module in modules:
                items = self.store.items(node.section, module)
                requires = self.store.requires(node.section, module)
                detail = f"requires: {', '.join(requires)}" if requires else ""

                rows.append(
                    Option(
                        preview_row(
                            module, f"{len(items)} item(s)", detail, widths, pal
                        )
                    )
                )
                rows.append(None)

            return rows[:-1] if rows else []

        if node.kind == "profile":
            config = self.store.plain()
            refs = self.store.profiles().get(node.name, [])
            width = max((len(r) for r in refs), default=0)

            rows = []
            for ref in refs:
                targets = spec.ref_targets(config, ref)
                resolved = ", ".join(f"{s}.{m}" for s, m in targets) or "(unresolved!)"
                arrow = "→" if targets else "✗"
                rows.append(Option(preview_row(ref, arrow, resolved, (width, 1), pal)))
            return rows

        if node.kind == "module":
            return module_preview(self.store, node.section, node.name, pal)

        if node.kind == "ref":
            return ref_preview(self.store, node.name, pal)

        item = self.store.items(node.section, node.name)[node.index]
        if isinstance(item, str):
            pairs = [("value", item)]
        else:
            order = spec.ITEM_FIELD_ORDER.get(node.section, ())
            keys = [k for k in order if k in item] + [k for k in item if k not in order]
            pairs = [(k, str(item[k])) for k in keys]

        return [Option(detail_lines(pairs, pal))]

    # REBUILD
    def rebuild(self, highlight: int = 0) -> None:
        pal = theme_palette(self.app)
        nav = self.query_one(NavList)
        parent = self.path[-1] if self.path else None

        self._nav_nodes = self._children(parent)
        nav.clear_options()

        options: list[Option | None] = [
            self._nav_option(node, pal) for node in self._nav_nodes
        ]

        if parent is None and len(options) > 1:
            # profiles are higher-level than the steps: divide them
            options.insert(1, None)
        nav.add_options(options)

        crumbs = [n.name or n.section for n in self.path]
        self.query_one("#nav-title", Static).update(
            Text(" / ".join(crumbs) or "Sections", style=f"bold {pal['title']}")
        )
        self.query_one("#footer", FooterBar).set_hints(self._footer_extras())

        if self._nav_nodes:
            nav.highlighted = min(highlight, len(self._nav_nodes) - 1)

        self.refresh_preview()

    def _footer_extras(self) -> list[tuple[str, str]]:
        parent = self.path[-1] if self.path else None

        if parent is None:
            return []

        if parent.kind == "section" and parent.section == "profiles":
            return [
                ("^n", "New"),
                ("^r", "Rename"),
                ("del", "Delete"),
                ("e", "Edit refs"),
            ]

        if parent.kind == "section":
            return [("^n", "New module"), ("e", "Requires"), ("del", "Delete")]

        if parent.kind == "module":
            return [("^n", "New"), ("^r", "Requires"), ("del", "Delete")]

        if parent.kind == "profile":
            return [("^n", "New"), ("del", "Delete")]

        return []

    def refresh_preview(self) -> None:
        if self._mode == "form":
            return  # the main panel is an overlay right now

        pal = theme_palette(self.app)
        nav = self.query_one(NavList)

        node = (
            self._nav_nodes[nav.highlighted]
            if self._nav_nodes and nav.highlighted is not None
            else None
        )

        self.query_one("#preview-title", Static).update(
            Text(self._preview_title(node), style=f"bold {pal['title']}")
        )

        preview = self.query_one(PreviewList)
        preview.clear_options()
        preview.add_options(self._preview_options(node, pal))

        if preview.option_count:
            preview.highlighted = 0

        crumbs = [n.name or n.section for n in self.path]
        selected = ""

        if node is not None:
            if node.kind == "item":
                item = self.store.items(node.section, node.name)[node.index]
                selected = spec.summarize_item(node.section, item)
            else:
                selected = node.name or node.section

        self.query_one(StatusLine).show(crumbs, selected)

    # NAVIGATION
    def _nav(self) -> NavList:
        return self.query_one(NavList)

    def _highlighted(self) -> Node | None:
        nav = self._nav()
        if not self._nav_nodes or nav.highlighted is None:
            return None

        return self._nav_nodes[nav.highlighted]

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id == "nav":
            self.refresh_preview()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "nav":
            self.descend()

    def descend(self) -> None:
        if self._mode:
            return

        node = self._highlighted()
        if node is None:
            return

        if node.kind == "item":
            self._open_form(node)
            return

        if node.kind == "ref":
            targets = spec.ref_targets(self.store.plain(), node.name)
            if targets:
                step, module = targets[0]
                self.path = [Node("section", step), Node("module", step, module)]
                self._history = [
                    1 + spec.STEP_ORDER.index(step),
                    self.store.module_names(step).index(module),
                ]
                self.rebuild()
            return

        self._history.append(self._nav().highlighted or 0)
        self.path.append(node)
        self.rebuild()

    def action_ascend(self) -> None:
        if self._mode:
            self.action_dismiss_overlay()
            return

        if not self.path:
            return

        restore = self._history.pop() if self._history else 0
        self.path.pop()
        self.rebuild(highlight=restore)

    # COMMAND LINE
    def _cmd(self) -> CmdLine:
        return self.query_one("#cmdline", CmdLine)

    def prompt(self, label: str, callback: Any, value: str = "") -> None:
        self._mode = "prompt"
        self._on_prompt = callback
        self._cmd().ask(label, value)
        self.query_one("#footer", FooterBar).set_hints(
            [], constant=[("enter", "OK"), ("esc", "Cancel")]
        )

    def confirm(self, question: str, callback: Any) -> None:
        pal = theme_palette(self.app)
        self._mode = "confirm"
        self._on_confirm = callback
        self._cmd().say(
            Text.assemble(
                (question, f"bold {pal['error']}"),
                ("   y", f"bold {pal['accent']}"),
                (" confirm  ", ""),
                ("esc", f"bold {pal['accent']}"),
                (" cancel", ""),
            )
        )
        self.query_one("#footer", FooterBar).set_hints(
            [], constant=[("y", "Confirm"), ("esc", "Cancel")]
        )

    def show_quit_line(self) -> None:
        pal = theme_palette(self.app)
        self._mode = "quit"
        self._cmd().say(
            Text.assemble(
                ("unsaved changes", f"bold {pal['accent']}"),
                ("   w", f"bold {pal['accent']}"),
                (" save and quit  ", ""),
                ("q", f"bold {pal['accent']}"),
                (" discard  ", ""),
                ("esc", f"bold {pal['accent']}"),
                (" cancel", ""),
            )
        )
        self.query_one("#footer", FooterBar).set_hints(
            [], constant=[("w", "Save+quit"), ("q", "Discard"), ("esc", "Cancel")]
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "cmd-input" and self._mode == "prompt":
            value = event.input.value.strip()
            callback = self._on_prompt
            self._close_cmdline()
            if value and callback:
                callback(value)

    def action_confirm_yes(self) -> None:
        if self._mode != "confirm":
            return

        callback = self._on_confirm
        self._close_cmdline()
        if callback:
            callback()

    def _close_cmdline(self) -> None:
        self._mode = None
        self._on_prompt = None
        self._on_confirm = None
        self._cmd().hide()
        self.query_one("#footer", FooterBar).set_hints(self._footer_extras())
        self._nav().focus()

    # ITEM FORM
    def _open_form(self, node: Node | None) -> None:
        """node=None means a blank 'new item' form for the current module."""
        pal = theme_palette(self.app)
        parent = self.path[-1] if self.path else None

        if node is None and (parent is None or parent.kind != "module"):
            return

        step = node.section if node else parent.section
        item: Any = (
            self.store.items(node.section, node.name)[node.index] if node else None
        )

        if isinstance(item, str):
            item = {BARE_FIELD.get(step, "value"): item}

        item = item or {}

        self._mode = "form"
        self._form_node = node
        self._form_step = step
        module = node.name if node else parent.name

        title = (
            f"edit {step}.{module} · item {node.index + 1}"
            if node
            else f"new {step}.{module} item"
        )
        self.query_one("#preview-title", Static).update(
            Text(title, style=f"bold {pal['title']}")
        )
        self.query_one("#preview").display = False

        form = self.query_one("#form", FormPanel)
        form.remove_children()
        form.mount(Static("", id="form-error"))
        first_input: Input | None = None

        for field in FORM_FIELDS[step]:
            value = item.get(field)
            form.mount(Label(field, classes="f-label"))
            widget = self._field_widget(field, value)
            form.mount(widget)
            if first_input is None and isinstance(widget, Input):
                first_input = widget

        form.display = True
        self.query_one("#footer", FooterBar).set_hints(
            [], constant=[("esc", "Cancel"), ("^s", "Save"), ("tab", "Next field")]
        )

        if first_input is not None:
            first_input.focus()

    @staticmethod
    def _field_widget(field: str, value: Any) -> Any:
        if field in ("copy", "sudo"):
            return Switch(value=bool(value), id=f"f-{field}")

        if field in ("enabled", "started"):
            current = "unset" if value is None else str(bool(value)).lower()
            return Select(TRISTATE, allow_blank=False, value=current, id=f"f-{field}")

        if field == "scope":
            return Select(
                [("system (default)", "system"), ("user", "user")],
                allow_blank=False,
                value=str(value or "system"),
                id=f"f-{field}",
            )

        if field == "label":
            options = [(name, name) for name in spec.XDG_LABELS]
            if value and value not in spec.XDG_LABELS:
                options.append((str(value), str(value)))
            kwargs: dict[str, Any] = {"allow_blank": True, "id": f"f-{field}"}

            if value:
                kwargs["value"] = str(value)
            return Select(options, **kwargs)

        if field == "content":
            return TextArea(str(value or ""), id=f"f-{field}")

        return Input(value=str(value or ""), id=f"f-{field}")

    def _collect_item(self, step: str) -> str | dict[str, Any]:
        """Read the form into a spec-valid item, preferring the minimal form
        (bare string when only the defining field is set)."""
        gathered: dict[str, Any] = {}

        for field in FORM_FIELDS[step]:
            widget = self.query_one(f"#f-{field}")
            if isinstance(widget, Switch):
                if widget.value:
                    gathered[field] = True

            elif isinstance(widget, TextArea):
                if widget.text:
                    gathered[field] = widget.text

            elif isinstance(widget, Select):
                value = widget.value
                if field in ("enabled", "started"):
                    if value != "unset":
                        gathered[field] = value == "true"
                elif field == "scope":
                    if value != "system":
                        gathered[field] = value
                elif isinstance(value, str) and value:
                    gathered[field] = value  # blank Select -> omit

            elif isinstance(widget, Input):
                if widget.value.strip():
                    gathered[field] = widget.value.strip()

        for field in REQUIRED_FIELDS[step]:
            if field not in gathered:
                raise FormError(f"`{field}` is required")

        if "mode" in gathered and not spec.is_octal_mode(gathered["mode"]):
            raise FormError(f"`mode` must be octal digits, got {gathered['mode']!r}")

        if step == "files" and "content" in gathered and "source" in gathered:
            raise FormError("`content` and `source` are mutually exclusive; clear one")

        bare = BARE_FIELD.get(step)
        if bare and list(gathered) == [bare]:
            item: str | dict[str, Any] = gathered[bare]
        else:
            item = gathered

        issues = spec.validate_item(step, item, "item")
        if issues:
            raise FormError(issues[0].message)

        return item

    def action_form_save(self) -> None:
        if self._mode != "form":
            return

        try:
            item = self._collect_item(self._form_step)
        except FormError as exc:
            pal = theme_palette(self.app)
            self.query_one("#form-error", Static).update(
                Text(str(exc), style=f"bold {pal['error']}")
            )
            return

        node = self._form_node
        parent = self.path[-1] if self.path else None

        if node is not None:
            self.store.update_item(node.section, node.name, node.index, item)
            keep = node.index
        else:
            self.store.add_item(parent.section, parent.name, item)
            keep = len(self.store.items(parent.section, parent.name)) - 1

        self.action_dismiss_overlay()
        self._mutated(highlight=keep)
        self.app.notify(f"updated {self._form_step} item")

    # DISMISS OVERLAY
    def action_dismiss_overlay(self) -> None:
        if self._mode in ("prompt", "confirm", "quit"):
            self._close_cmdline()
        elif self._mode == "form":
            self._mode = None
            self._form_node = None
            form = self.query_one("#form", FormPanel)
            form.display = False
            form.remove_children()
            self.query_one("#preview").display = True
            self.query_one("#footer", FooterBar).set_hints(self._footer_extras())
            self._nav().focus()
            self.refresh_preview()

    # LEVEL-AWARE EDITOR TRIGGERS
    def _open_ref_picker(
        self, title: str, selected: list[str], apply: Any, exclude: str = ""
    ) -> None:
        choices = [
            ref
            for ref in spec.ref_choices(self.store.plain(), extra=selected)
            if ref != exclude
        ]

        def done(refs: list[str] | None) -> None:
            if refs is not None:
                apply(refs)
                self._mutated()
                self.app.notify(f"set {len(refs)} ref(s)")

        self.app.push_screen(
            RefPickerScreen(self.store, title, choices, selected), done
        )

    def _edit_profile_refs(self, profile: str) -> None:
        self._open_ref_picker(
            f"refs › {profile}",
            self.store.profiles().get(profile, []),
            lambda refs: self.store.set_profile(profile, refs),
        )

    def _edit_requires(self, step: str, module: str) -> None:
        self._open_ref_picker(
            f"requires › {step}.{module}",
            self.store.requires(step, module),
            lambda refs: self.store.set_requires(step, module, refs),
            exclude=f"{step}.{module}",
        )

    def action_edit(self) -> None:
        if self._mode:
            return

        node = self._highlighted()
        if node is None:
            return

        if node.kind == "item":
            self._open_form(node)
        elif node.kind == "profile":
            self._edit_profile_refs(node.name)
        elif node.kind == "module":
            self._edit_requires(node.section, node.name)
        elif node.kind == "ref" and self.path and self.path[-1].kind == "profile":
            self._edit_profile_refs(self.path[-1].name)

    def action_new(self) -> None:
        if self._mode:
            return

        parent = self.path[-1] if self.path else None
        if parent is None:
            self.app.notify("open a section first (profiles or a step)")
            return

        if parent.kind == "section" and parent.section == "profiles":
            self.prompt("new profile name", self._create_profile)
        elif parent.kind == "section":
            step = parent.section
            self.prompt(
                f"new {step} module name",
                lambda name: self._create_module(step, name),
            )
        elif parent.kind == "profile":
            self._edit_profile_refs(parent.name)
        elif parent.kind == "module":
            self._open_form(None)

    def _create_profile(self, name: str) -> None:
        if name in self.store.profiles():
            self.app.notify(f"profile `{name}` already exists", severity="error")
            return

        self.store.set_profile(name, [])
        self._mutated(highlight=len(self.store.profiles()) - 1)
        self._edit_profile_refs(name)

    def _create_module(self, step: str, name: str) -> None:
        try:
            self.store.add_module(step, name)
        except StoreError as exc:
            self.app.notify(str(exc), severity="error")
            return

        self._mutated(highlight=len(self.store.module_names(step)) - 1)

    def action_rename_or_requires(self) -> None:
        if self._mode:
            return

        node = self._highlighted()
        parent = self.path[-1] if self.path else None
        if node is not None and node.kind == "profile":
            self.prompt(
                f"rename profile `{node.name}` to",
                lambda new: self._rename_profile(node.name, new),
                value=node.name,
            )
        elif node is not None and node.kind == "module":
            self._edit_requires(node.section, node.name)
        elif parent is not None and parent.kind == "module":
            self._edit_requires(parent.section, parent.name)

    def _rename_profile(self, old: str, new: str) -> None:
        if new == old:
            return

        try:
            self.store.rename_profile(old, new)
        except StoreError as exc:
            self.app.notify(str(exc), severity="error")
            return

        self._mutated(highlight=len(self.store.profiles()) - 1)

    def action_delete(self) -> None:
        if self._mode:
            return

        node = self._highlighted()
        if node is None or node.kind == "section":
            return

        index = self._nav().highlighted or 0
        if node.kind == "item":
            item = self.store.items(node.section, node.name)[node.index]
            label = spec.summarize_item(node.section, item)
        else:
            label = node.name

        self.confirm(
            f"delete {node.kind} `{label}`?",
            lambda: self._delete_node(node, index),
        )

    def _delete_node(self, node: Node, index: int) -> None:
        try:
            if node.kind == "profile":
                self.store.remove_profile(node.name)
            elif node.kind == "module":
                self.store.remove_module(node.section, node.name)
            elif node.kind == "item":
                self.store.remove_item(node.section, node.name, node.index)
            elif node.kind == "ref":
                profile = self.path[-1].name
                refs = self.store.profiles().get(profile, [])
                refs.remove(node.name)
                self.store.set_profile(profile, refs)

        except (StoreError, ValueError) as exc:
            self.app.notify(str(exc), severity="error")
            return

        self._mutated(highlight=index)
        self.app.notify(f"deleted {node.kind} `{node.name or 'item'}`")


class ConfigEditorApp(App[None]):
    """The wired two-panel editor over one config.toml file."""

    TITLE = "dotfiles-et-al config editor"

    BINDINGS: ClassVar = [
        # Priority so the palette stays reachable from modal screens;
        # printable keys like `:` still type into focused Inputs.
        *pair(
            "global.palette", "command_palette", "Commands", show=False, priority=True
        ),
        *pair("global.save", "save", "Save", show=False),
        *pair("global.validate", "validate", "Validate", show=False),
        *pair("global.quit", "quit", "Quit", show=False),
    ]

    CSS = """
    HeaderBar {
        dock: top;
        height: 1;
        background: $panel;
        content-align: center middle;
    }
    FooterBar {
        dock: bottom;
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    CmdLine {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    #cmd-label { width: auto; }
    #cmd-input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: $surface;
    }
    #cmd-input:focus { border: none; background: $surface; }
    #sidebar {
        width: 34;
        border-right: solid $panel;   /* the single shared divider */
        padding: 0 1;
    }
    #main {
        width: 1fr;
        padding: 0 1;
    }
    #nav-title, #preview-title {
        height: 2;
        padding: 1 1 0 1;
    }
    #status {
        height: 1;
        padding: 0 1;
    }
    NavList, PreviewList, PickerList,
    NavList:focus, PickerList:focus {
        background: transparent;
        border: none;
        height: 1fr;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
    }
    ValidationScreen {
        align: center middle;
    }
    #val-box {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: round $panel;
        padding: 1 2;
    }
    #val-title { height: 2; }
    #val-issues { height: auto; max-height: 20; }
    #val-issues Static { height: auto; margin-bottom: 1; }
    #val-hint { height: 1; }
    FormPanel {
        height: 1fr;
        padding: 0 1;
    }
    FormPanel .f-label {
        color: $primary;
        margin-top: 1;
    }
    #form-error { height: auto; }
    FormPanel Input, FormPanel Select {
        width: 60;
        max-width: 100%;
        height: 1;
        padding: 0 1;
        background: $boost;
        border: none;
    }
    FormPanel Input:focus, FormPanel Select:focus {
        background: $primary 30%;
        border: none;
    }
    FormPanel SelectCurrent { border: none; padding: 0; }
    FormPanel TextArea {
        height: 6;
        width: 80;
        max-width: 100%;
        background: $boost;
        border: none;
    }
    FormPanel TextArea:focus {
        background: $primary 20%;
        border: none;
    }
    """

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store

    def on_mount(self) -> None:
        self.theme = load_theme()
        keymap, warnings = load_user_keymap()
        if keymap:
            self.set_keymap(keymap)
        for warning in warnings:
            self.notify(warning, severity="warning")
        self.push_screen(EditorScreen(self.store))

    def watch_theme(self, _theme: str) -> None:
        """Persist the choice, and rebuild Rich-rendered content whose colors
        were resolved from the previous theme at build time. CSS re-resolves
        its own variables automatically."""
        save_theme(self.theme)
        for screen in self.screen_stack:
            refresh = getattr(screen, "on_theme_refresh", None)
            if refresh is not None:
                refresh()
            screen.refresh()

    def save_config(self) -> bool:
        """Validate (warn, don't block), save; True on success."""
        issues = spec.validate_config(self.store.plain())
        if issues:
            self.notify(
                f"saved with {len(issues)} validation issue(s) — press v to review",
                severity="warning",
            )

        try:
            self.store.save()
        except StoreError as exc:
            self.notify(str(exc), severity="error")
            return False

        for header in self.query(HeaderBar):
            header.refresh()

        if not issues:
            self.notify(f"saved {self.store.path}")

        return True

    def action_save(self) -> None:
        screen = self.screen
        if isinstance(screen, EditorScreen):
            if screen._mode == "form":
                screen.action_form_save()
                return

            if screen._mode == "quit":  # `w` on the quit line: write+exit
                screen._close_cmdline()
                if self.save_config():
                    self.exit()
                return

            if screen._mode is not None:  # prompt/confirm up
                return

        self.save_config()

    def action_validate(self) -> None:
        if isinstance(self.screen, ValidationScreen):
            return

        self.push_screen(ValidationScreen(spec.validate_config(self.store.plain())))

    def action_quit(self) -> None:
        """Three-way quit line when there are unsaved changes."""
        screen = self.screen
        if isinstance(screen, EditorScreen):
            if screen._mode == "quit":  # q on the quit line = discard
                self.exit()
                return

            if screen._mode is not None:
                return  # an overlay is up; ignore

            if self.store.dirty:
                screen.show_quit_line()
                return

        self.exit()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Palette entries, in a fixed order with vim-ex-style prefixes."""
        stock = {c.title.lower(): c for c in super().get_system_commands(screen)}

        def relabel(key: str, label: str) -> Iterable[SystemCommand]:
            command = stock.get(key)
            if command is not None:
                yield SystemCommand(label, command.help, command.callback)

        yield from relabel("keys", "k — Keys")
        yield SystemCommand(
            "b — Edit keybinds",
            f"Both key sets are remappable in {keybinds_path()}",
            self._notify_keybinds_path,
        )
        yield SystemCommand(
            "v — Validate config",
            "Check the config against the spec",
            self.action_validate,
        )
        yield from relabel("theme", "t — Theme")
        yield from relabel("screenshot", "svg — Screenshot")
        yield SystemCommand("w — Save", f"Save {self.store.path}", self.save_config)
        yield SystemCommand(
            "wq — Save and quit", "Save, then exit", self._save_and_quit
        )
        yield SystemCommand("q — Quit", "Exit (confirms if unsaved)", self.action_quit)
        yield SystemCommand(
            "q! — Quit without saving", "Discard changes and exit", self.exit
        )

    def _save_and_quit(self) -> None:
        if self.save_config():
            self.exit()

    def _notify_keybinds_path(self) -> None:
        self.notify(
            f"edit [native]/[vim] tables in {keybinds_path()} "
            "(see keybinds.example.toml in the repo)"
        )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from config_tui.__main__ import default_config_path

    path = Path(argv[0]) if argv else default_config_path()
    if path is None or not path.is_file():
        print("no config.toml found; pass a path", file=sys.stderr)
        return 1

    try:
        store = ConfigStore(path)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    ConfigEditorApp(store).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
