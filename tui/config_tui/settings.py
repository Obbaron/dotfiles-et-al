"""Persisted UI preferences for dotfiles-tui."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import tomlkit

DEFAULT_THEME = "catppuccin-mocha"


def settings_path() -> Path:
    """Location of the persisted UI settings file."""
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return xdg / "dotfiles-et-al" / "tui-settings.toml"


def load_settings(path: Path | None = None) -> dict[str, object]:
    """Return the settings mapping, or {} if absent/unreadable/malformed."""
    path = path or settings_path()
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def load_theme(path: Path | None = None) -> str:
    """The persisted theme name, or the default when none is stored."""
    value = load_settings(path).get("theme")
    return value if isinstance(value, str) and value else DEFAULT_THEME


def save_theme(theme: str, path: Path | None = None) -> None:
    """Persist the chosen theme, merging into any existing settings.

    Best-effort: failure to write (e.g. an unwritable config dir) is
    swallowed so it never interrupts the session.
    """
    path = path or settings_path()
    data = load_settings(path)
    data["theme"] = theme
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            fh.write(tomlkit.dumps(data))
    except OSError:
        pass
