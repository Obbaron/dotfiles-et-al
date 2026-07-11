"""CLI entry point: resolve the config path, load the store, run the app."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from config_tui.store import ConfigStore, StoreError
from config_tui.ui import ConfigEditorApp


def default_config_path() -> Path | None:
    """The config to edit when none is given.

    Prefers the live per-machine config seeded by configure.py, then falls back
    to a config.toml in the current directory (repo template).
    """
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    candidates = (
        xdg / "dotfiles-et-al" / "config.toml",
        Path.cwd() / "config.toml",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tui",
        description="Two-panel TUI editor for a dotfiles-et-al config.toml.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        help=(
            "path to the config.toml to edit "
            "(default: $XDG_CONFIG_HOME/dotfiles-et-al/config.toml, then ./config.toml)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    path = args.config or default_config_path()
    if path is None:
        print(
            "no config.toml found; pass a path or run configure.py once to seed one",
            file=sys.stderr,
        )
        return 1
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
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
