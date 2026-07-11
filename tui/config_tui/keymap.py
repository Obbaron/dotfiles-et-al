"""Action-to-key mapping: two parallel key sets over one set of actions.

Every user-facing action has an id (``context.action``) and two default key
assignments: **native** (arrows, ctrl-chords, enter/escape) and **vim**
(hjkl, single letters, g/G). Both sets are always active; each becomes its
own Textual ``Binding`` with id ``<action>.native`` / ``<action>.vim``.

Users can remap either set in ``$XDG_CONFIG_HOME/dotfiles-et-al/keybinds.toml``:

    [native]
    "global.save" = "ctrl+s"

    [vim]
    "browse.open" = "l,space"

Keys are Textual key names; comma-separate alternatives. Unknown action ids
are reported, not fatal.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from textual.binding import Binding

# action id -> (native keys, vim keys)
# NOTE: Comma-separated keys are alternatives
DEFAULT_KEYS: dict[str, tuple[str, str]] = {
    # global (always active; letters are consumed first by focused text widgets)
    # `:` opens the palette vim-style; inside a text field `:` types a colon, so
    # ctrl+: is the escape hatch; ctrl+p always works.
    "global.palette": ("ctrl+p", "colon,ctrl+colon"),
    "global.save": ("ctrl+s", "w"),
    "global.quit": ("ctrl+q", "q"),
    "global.validate": ("ctrl+v", "v"),
    # navigation (bound on the nav list widget)
    "browse.down": ("down", "j"),
    "browse.up": ("up", "k"),
    "browse.first": ("home", "g"),
    "browse.last": ("end", "G"),
    "browse.page_down": ("pagedown", "ctrl+d"),
    "browse.page_up": ("pageup", "ctrl+u"),
    "browse.open": ("right,enter", "l"),
    "browse.back": ("left,escape", "h"),
    # level-aware editor actions (depends on highlighted node)
    "actions.edit": ("e", "e"),
    "actions.new": ("ctrl+n", "n"),
    "actions.rename": ("ctrl+r", "r"),  # rename profile / edit requires
    "actions.delete": ("delete", "d"),
    # ref picker (toggleable list with live preview)
    "picker.down": ("down", "j"),
    "picker.up": ("up", "k"),
    "picker.first": ("home", "g"),
    "picker.last": ("end", "G"),
    "picker.toggle": ("space,right", "l"),
    "picker.accept": ("enter", "enter"),
    "picker.cancel": ("escape,left", "h"),
    # item form (fields focused: chords only)
    "form.save": ("ctrl+s", "ctrl+w"),
    "form.cancel": ("escape", "ctrl+q"),
}


def keybinds_path() -> Path:
    """Location of the user's keybind overrides."""
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return xdg / "dotfiles-et-al" / "keybinds.toml"


def pair(
    action_id: str,
    action: str,
    description: str,
    *,
    show: bool = True,
    priority: bool = False,
    key_display: str | None = None,
    action_native: str | None = None,
    action_vim: str | None = None,
) -> list[Binding]:
    """Pair native+vim keybinds for one action"""
    native_keys, vim_keys = DEFAULT_KEYS[action_id]
    return [
        Binding(
            native_keys,
            action_native or action,
            description,
            show=show,
            priority=priority,
            key_display=key_display,
            id=f"{action_id}.native",
        ),
        Binding(
            vim_keys,
            action_vim or action,
            description,
            show=False,
            priority=priority,
            id=f"{action_id}.vim",
        ),
    ]


def load_user_keymap(path: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """Read keybinds.toml into a Textual keymap ({binding_id: keys}).

    Returns the keymap plus a list of human-readable warnings for entries
    that could not be applied.
    """
    path = path or keybinds_path()
    if not path.is_file():
        return {}, []

    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, [f"keybinds: cannot read {path}: {exc}"]

    keymap: dict[str, str] = {}
    warnings: list[str] = []
    for set_name in ("native", "vim"):
        table = data.get(set_name, {})
        if not isinstance(table, dict):
            warnings.append(f"keybinds: [{set_name}] must be a table")
            continue

        for action_id, keys in table.items():
            if action_id not in DEFAULT_KEYS:
                warnings.append(
                    f"keybinds: unknown action {action_id!r} in [{set_name}]"
                )
            elif not isinstance(keys, str) or not keys:
                warnings.append(
                    f"keybinds: {action_id} in [{set_name}] must be a non-empty key string"
                )
            else:
                keymap[f"{action_id}.{set_name}"] = keys

    for extra in data:
        if extra not in ("native", "vim"):
            warnings.append(
                f"keybinds: unknown table [{extra}] (expected [native]/[vim])"
            )

    return keymap, warnings
